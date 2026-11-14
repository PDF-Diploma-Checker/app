"""Word-only proposals and an atomic, offline-capable approved dictionary cache."""
import json
import logging
import os
from pathlib import Path
import tempfile
import threading
import unicodedata
from urllib.parse import urlsplit

import requests
from common.path import DATA_DIR

logger = logging.getLogger(__name__)
_lock = threading.Lock()
_words = frozenset()
DEFAULT_SERVICE_URL = "https://diploma-checker-dictionary.diplomachecker.workers.dev"


def normalize_word(value):
    if not isinstance(value, str):
        raise ValueError('Enter one word')
    word = unicodedata.normalize('NFC', value).strip().casefold()
    if not 1 <= len(word) <= 80 or not all(c.isalpha() or c in "-'’" for c in word) or not word[0].isalpha() or not word[-1].isalpha():
        raise ValueError('Enter one word (up to 80 letters)')
    return word


def service_url():
    # An explicit empty override disables remote dictionary requests.
    url = os.environ.get('DIPLOMACHECKER_DICTIONARY_URL', DEFAULT_SERVICE_URL).rstrip('/')
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.netloc or parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError('Shared dictionary is not configured. Contact the application administrator.')
    return url


def cache_path():
    return Path(DATA_DIR) / 'approved_dictionary.json'


def validated_words(data):
    if not isinstance(data, dict) or not isinstance(data.get('words'), list) or len(data['words']) > 100000:
        raise ValueError('Invalid shared dictionary')
    return frozenset(normalize_word(word) for word in data['words'])


def sync():
    """Called on the analysis worker before checking words. Never discard an offline cache."""
    global _words
    with _lock:
        try:
            _words = validated_words(json.loads(cache_path().read_text(encoding='utf-8')))
        except (OSError, ValueError):
            pass
        try:
            url = service_url()
        except ValueError:
            return False
        try:
            with requests.get(url + '/words', timeout=(3, 8), stream=True, allow_redirects=False) as response:
                response.raise_for_status()
                if response.status_code != 200:
                    raise ValueError('Unexpected dictionary response')
                payload = bytearray()
                for chunk in response.iter_content(65536):
                    payload.extend(chunk)
                    if len(payload) > 10_000_000:
                        raise ValueError('Dictionary response too large')
                words = validated_words(json.loads(payload))
            path = cache_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as file:
                    temporary = file.name
                    json.dump({'words': sorted(words)}, file, ensure_ascii=False)
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
            _words = words
            return True
        except (requests.RequestException, OSError, ValueError):
            logger.warning('Shared dictionary unavailable; using last approved cache')
            return False


def contains(word):
    return unicodedata.normalize('NFC', word).casefold() in _words


def propose(word):
    # Never include a finding, PDF path, sentence, logs, or thesis attachment.
    response = requests.post(service_url() + '/proposals', json={'word': normalize_word(word)}, timeout=(3, 10), allow_redirects=False)
    if response.status_code != 201:
        raise ValueError(f'Proposal could not be submitted ({response.status_code}). Please try again later.')
    data = response.json()
    if data.get('status') not in ('pending', 'approved', 'rejected'):
        raise ValueError('Invalid proposal response')
    return data['status']
