"""Standalone moderated dictionary service. Run behind an HTTPS reverse proxy."""
from contextlib import contextmanager
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import unicodedata
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def normalize_word(value):
    if not isinstance(value, str):
        raise ValueError('Word must be text')
    word = unicodedata.normalize('NFC', value).strip().casefold()
    if not 1 <= len(word) <= 80 or not all(c.isalpha() or c in "-'’" for c in word) or not word[0].isalpha() or not word[-1].isalpha():
        raise ValueError('Enter one word (up to 80 letters)')
    return word


class Store:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS proposals (
                    id INTEGER PRIMARY KEY, word TEXT UNIQUE NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    reviewed TEXT, reviewer TEXT);
                CREATE TABLE IF NOT EXISTS rate_limits (
                    address TEXT, day TEXT, count INTEGER NOT NULL,
                    PRIMARY KEY(address, day));
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def propose(self, word, address):
        word = normalize_word(word)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Store a hash rather than a raw client address; bounded daily abuse budget.
            address = hashlib.sha256(address.encode()).hexdigest()
            db.execute("DELETE FROM rate_limits WHERE day < date('now', '-2 days')")
            row = db.execute("SELECT count FROM rate_limits WHERE address=? AND day=date('now')", (address,)).fetchone()
            if row and row[0] >= 30:
                raise OverflowError('Daily proposal limit reached')
            db.execute("INSERT INTO rate_limits VALUES (?,date('now'),1) ON CONFLICT(address,day) DO UPDATE SET count=count+1", (address,))
            db.execute('INSERT OR IGNORE INTO proposals(word) VALUES (?)', (word,))
            return dict(zip(('id', 'status'), db.execute('SELECT id,status FROM proposals WHERE word=?', (word,)).fetchone()))

    def queue(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM proposals WHERE status='pending' ORDER BY id LIMIT 200")]

    def review(self, proposal_id, decision, reviewer):
        if decision not in ('approved', 'rejected'):
            raise ValueError('Invalid decision')
        with self.connect() as db:
            result = db.execute("UPDATE proposals SET status=?,reviewed=CURRENT_TIMESTAMP,reviewer=? WHERE id=? AND status='pending'", (decision, reviewer, proposal_id))
            if result.rowcount != 1:
                raise LookupError('Proposal missing or already reviewed')

    def words(self):
        with self.connect() as db:
            return [r[0] for r in db.execute("SELECT word FROM proposals WHERE status='approved' ORDER BY word")]


def handler(store, username, salt, password_hash):
    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup()
            self.connection.settimeout(15)

        def log_message(self, *_):
            pass  # Do not log credentials or submitted words.

        def reply(self, status, data, content_type='application/json'):
            body = data.encode() if isinstance(data, str) else json.dumps(data).encode()
            self.send_response(status)
            self.send_header('Content-Type', content_type + '; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('X-Frame-Options', 'DENY')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authenticated(self):
            try:
                scheme, token = self.headers.get('Authorization', '').split(' ', 1)
                user, password = base64.b64decode(token, validate=True).decode().split(':', 1)
                valid = scheme == 'Basic' and hmac.compare_digest(user, username) and hmac.compare_digest(hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex(), password_hash)
            except (ValueError, UnicodeError):
                valid = False
            if not valid:
                self.send_response(401)
                self.send_header('WWW-Authenticate', 'Basic realm="Dictionary review", charset="UTF-8"')
                self.send_header('Content-Length', '0')
                self.end_headers()
            return valid

        def do_GET(self):
            if self.path == '/words':
                return self.reply(200, {'words': store.words()})
            if self.path in ('/admin', '/admin.js', '/admin/queue'):
                if not self.authenticated():
                    return
                if self.path == '/admin/queue':
                    return self.reply(200, store.queue())
                name = 'admin.html' if self.path == '/admin' else 'admin.js'
                return self.reply(200, Path(__file__).with_name(name).read_text(), 'text/html' if name.endswith('html') else 'text/javascript')
            self.reply(404, {'error': 'Not found'})

        def do_POST(self):
            if self.path not in ('/proposals', '/admin/review'):
                return self.reply(404, {'error': 'Not found'})
            if self.path.startswith('/admin'):
                if not self.authenticated():
                    return
                # A cross-origin form cannot set this header; no CORS is enabled.
                if self.headers.get('X-Dictionary-Review') != '1':
                    return self.reply(403, {'error': 'Missing review header'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 1024:
                    return self.reply(413, {'error': 'Invalid request size'})
                if self.headers.get_content_type() != 'application/json':
                    return self.reply(415, {'error': 'JSON required'})
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError('Object required')
                if self.path == '/proposals':
                    if set(data) != {'word'}:
                        raise ValueError('Only a word is accepted; do not send document context')
                    return self.reply(201, store.propose(data['word'], self.client_address[0]))
                if set(data) != {'id', 'decision'} or type(data['id']) is not int:
                    raise ValueError('Invalid review')
                store.review(data['id'], data['decision'], username)
                self.reply(200, {'status': data['decision']})
            except (ValueError, KeyError, UnicodeError) as error:
                self.reply(400, {'error': str(error)})
            except LookupError as error:
                self.reply(409, {'error': str(error)})
            except OverflowError as error:
                self.reply(429, {'error': str(error)})
    return Handler


def main():
    username = os.environ['DICTIONARY_ADMIN_USER']
    salt = bytes.fromhex(os.environ['DICTIONARY_ADMIN_SALT'])
    password_hash = os.environ['DICTIONARY_ADMIN_HASH']
    if not username or len(salt) < 16 or len(bytes.fromhex(password_hash)) != 64:
        raise ValueError('Invalid admin configuration')
    store = Store(os.environ.get('DICTIONARY_DB', 'dictionary.sqlite3'))
    server = ThreadingHTTPServer((os.environ.get('DICTIONARY_BIND', '127.0.0.1'), int(os.environ.get('PORT', '8080'))), handler(store, username, salt, password_hash))
    server.serve_forever()


if __name__ == '__main__':
    main()
