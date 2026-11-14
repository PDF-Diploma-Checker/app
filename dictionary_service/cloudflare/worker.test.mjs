import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { readFileSync } from 'node:fs';
import { pbkdf2Sync, createHmac } from 'node:crypto';
import worker, { normalizeWord } from './worker.mjs';

// Executes the actual schema and every Worker SQL statement in SQLite, with
// D1's ordered, atomic batch contract. No SQL-pattern emulation.
class D1 {
  constructor() {
    this.db = new DatabaseSync(':memory:');
    this.db.exec(readFileSync(new URL('./schema.sql', import.meta.url), 'utf8'));
  }
  prepare(query) {
    const statement = this.db.prepare(query);
    const bound = args => ({
      all: async () => ({ results: statement.all(...args) }),
      run: async () => ({ meta: { changes: Number(statement.run(...args).changes) } }),
      query, args,
    });
    return { ...bound([]), bind: (...args) => bound(args) };
  }
  async batch(statements) {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const results = statements.map(({ query, args }) => ({ results: this.db.prepare(query).all(...args) }));
      this.db.exec('COMMIT'); return results;
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
  }
}
const password = 'zażółć:🔑';
function setup() {
  const env = { DB: new D1(), DICTIONARY_ADMIN_USER: 'praha6248', DICTIONARY_ADMIN_SALT: 'ab'.repeat(16), RATE_LIMIT_SALT: 'cd'.repeat(32) };
  env.DICTIONARY_ADMIN_HASH = pbkdf2Sync(password, Buffer.from(env.DICTIONARY_ADMIN_SALT, 'hex'), 100000, 32, 'sha256').toString('hex');
  const auth = 'Basic ' + Buffer.from(`${env.DICTIONARY_ADMIN_USER}:${password}`, 'utf8').toString('base64');
  const call = (path, { method = 'GET', data, headers = {}, raw } = {}) => worker.fetch(new Request(`https://dictionary.test${path}`, {
    method, headers: { 'CF-Connecting-IP': '203.0.113.8', ...(data !== undefined || raw !== undefined ? { 'Content-Type': 'application/json' } : {}), ...headers },
    body: raw ?? (data !== undefined ? JSON.stringify(data) : undefined),
  }), env);
  const proposal = word => call('/proposals', { method: 'POST', data: { word } });
  const review = (id, decision) => call('/admin/review', { method: 'POST', data: { id, decision }, headers: { Authorization: auth, 'X-Dictionary-Review': '1' } });
  return { env, auth, call, proposal, review };
}
test('Python normalization: NFC, casefold, Unicode letters, punctuation, codepoint length', () => {
  for (const [input, expected] of [['  ZAŻÓŁĆ ', 'zażółć'], ['Straße', 'strasse'], ['ΟΣ', 'οσ'], ['e\u0301', 'é'], ['\u001cWord\u0085', 'word'], ['a--b', 'a--b'], ["L’ŒUVRE", 'l’œuvre'], ['𐐀'.repeat(80), '𐐨'.repeat(80)]]) assert.equal(normalizeWord(input), expected);
  for (const input of ['', '-abc', 'abc-', 'a b', 'a1', 'a_b', 'a\u0301\u0301', '\ufeffword', '𐐀'.repeat(81), null, 12]) assert.throws(() => normalizeWord(input));
});
test('native client API lifecycle; duplicate and final decisions', async () => {
  const { call, proposal, review, auth } = setup();
  assert.deepEqual(await (await call('/words')).json(), { words: [] });
  const response = await proposal('ŻÓŁĆ'); assert.equal(response.status, 201);
  const item = await response.json(); assert.deepEqual(item, { id: 1, status: 'pending' });
  assert.deepEqual(await (await proposal('żółć')).json(), item);
  const queue = await (await call('/admin/queue', { headers: { Authorization: auth } })).json();
  assert.equal(queue.length, 1); assert.equal(queue[0].word, 'żółć'); assert.equal(queue[0].reviewed, null);
  assert.equal((await review(1, 'approved')).status, 200);
  assert.equal((await review(1, 'rejected')).status, 409);
  assert.deepEqual(await (await call('/words')).json(), { words: ['żółć'] });
  assert.deepEqual(await (await proposal('ŻÓŁĆ')).json(), { id: 1, status: 'approved' });
  const rejected = await (await proposal('other')).json();
  assert.equal((await review(rejected.id, 'rejected')).status, 200);
  assert.deepEqual(await (await proposal('other')).json(), { id: rejected.id, status: 'rejected' });
  assert.deepEqual(await (await call('/admin/queue', { headers: { Authorization: auth } })).json(), []);
});
test('admin is protected for all methods; UTF-8 Basic, review header, malformed auth', async () => {
  const { call, auth } = setup();
  for (const path of ['/admin', '/admin.js', '/admin/queue', '/admin/review', '/admin/unknown']) {
    for (const method of ['GET', 'POST', 'OPTIONS']) {
      const response = await call(path, { method }); assert.equal(response.status, 401);
      assert.match(response.headers.get('WWW-Authenticate'), /UTF-8/);
    }
  }
  for (const Authorization of ['Basic ???', 'Basic /w==', 'Bearer abc', 'Basic ' + Buffer.from('praha6248:wrong').toString('base64'), 'Basic ' + Buffer.from('other:wrong').toString('base64')]) {
    assert.equal((await call('/admin/queue', { headers: { Authorization } })).status, 401);
  }
  assert.equal((await call('/admin/queue', { headers: { Authorization: auth } })).status, 200);
  assert.equal((await call('/admin/review', { method: 'POST', data: { id: 1, decision: 'approved' }, headers: { Authorization: auth } })).status, 403);
});
test('word-only payloads, body bounds, content type, safe errors and no CORS', async () => {
  const { call, auth } = setup();
  for (const data of [{ word: 'word', context: 'private thesis' }, {}, [], null, { word: 2 }, { word: 'two words' }]) {
    assert.equal((await call('/proposals', { method: 'POST', data })).status, 400);
  }
  for (const [raw, headers, expected] of [['{', {}, 400], ['x'.repeat(1025), {}, 413], ['', {}, 413], ['{}', { 'Content-Type': 'text/plain' }, 415], ['{}', { 'Content-Length': '2048' }, 413], ['{}', { 'Content-Length': '1' }, 413]]) {
    const response = await call('/proposals', { method: 'POST', raw, headers }); assert.equal(response.status, expected);
    assert.equal(response.headers.get('Access-Control-Allow-Origin'), null);
    assert.equal(response.headers.get('Cache-Control'), 'no-store');
    assert.equal(response.headers.get('X-Content-Type-Options'), 'nosniff');
  }
  for (const data of [{ id: true, decision: 'approved' }, { id: 1, decision: 'pending' }, { id: 1, decision: 'approved', extra: 1 }]) {
    assert.equal((await call('/admin/review', { method: 'POST', data, headers: { Authorization: auth, 'X-Dictionary-Review': '1' } })).status, 400);
  }
  assert.equal((await call('/proposals', { method: 'OPTIONS' })).status, 404);
});
test('30 concurrent proposals per hashed IP/day; no insertion after budget; cleanup', async () => {
  const { env, call, proposal } = setup();
  env.DB.db.exec("INSERT INTO rate_limits VALUES('old','2000-01-01',30)");
  const responses = await Promise.all(Array.from({ length: 40 }, (_, i) => proposal('word' + String.fromCharCode(97 + Math.floor(i / 26), 97 + i % 26))));
  assert.equal(responses.filter(r => r.status === 201).length, 30);
  assert.equal(responses.filter(r => r.status === 429).length, 10);
  assert.equal(env.DB.db.prepare('SELECT count(*) n FROM proposals').get().n, 30);
  const rows = env.DB.db.prepare('SELECT * FROM rate_limits').all(); assert.equal(rows.length, 1);
  assert.equal(rows[0].address, createHmac('sha256', Buffer.from(env.RATE_LIMIT_SALT, 'hex')).update('203.0.113.8').digest('hex'));
  assert.equal(rows[0].count, 31);
  assert.equal((await call('/proposals', { method: 'POST', data: { word: 'new' }, headers: { 'CF-Connecting-IP': '203.0.113.9' } })).status, 201);
  env.DB.db.exec("UPDATE rate_limits SET day='2000-01-01'");
  assert.equal((await proposal('fresh')).status, 201);
});
test('concurrent duplicate inserts and moderation preserve unique/final state', async () => {
  const { env, proposal, review } = setup();
  const responses = await Promise.all(Array.from({ length: 15 }, () => proposal('same')));
  for (const response of responses) assert.deepEqual(await response.json(), { id: 1, status: 'pending' });
  assert.equal(env.DB.db.prepare('SELECT count(*) n FROM proposals').get().n, 1);
  const decisions = await Promise.all([review(1, 'approved'), review(1, 'rejected')]);
  assert.deepEqual(decisions.map(r => r.status).sort(), [200, 409]);
});
test('batch SQL failures roll back rate increments and insertion; exceptions stay private', async () => {
  const { env, proposal, call } = setup();
  env.DB.db.exec("CREATE TRIGGER fail_insert BEFORE INSERT ON proposals BEGIN SELECT RAISE(ABORT,'secret SQL detail'); END");
  const response = await proposal('privateword'); assert.equal(response.status, 500);
  assert.deepEqual(await response.json(), { error: 'Internal server error' });
  assert.equal(env.DB.db.prepare('SELECT count(*) n FROM rate_limits').get().n, 0);
  env.DB.db.exec('DROP TRIGGER fail_insert');
  assert.equal((await call('/proposals', { method: 'POST', data: { word: 'valid' }, headers: { 'CF-Connecting-IP': '' } })).status, 503);
  // Public reads never need admin configuration or PBKDF2.
  delete env.DICTIONARY_ADMIN_SALT; delete env.DICTIONARY_ADMIN_HASH;
  assert.equal((await call('/words')).status, 200);
});
test('queue is oldest 200 pending rows and approved export is sorted', async () => {
  const { env, call, auth } = setup();
  const insert = env.DB.db.prepare('INSERT INTO proposals(word,status) VALUES(?,?)');
  for (let i = 0; i < 205; i++) insert.run('word' + i, 'pending');
  insert.run('zeta', 'approved'); insert.run('alpha', 'approved'); insert.run('hidden', 'rejected');
  const queue = await (await call('/admin/queue', { headers: { Authorization: auth } })).json();
  assert.equal(queue.length, 200); assert.equal(queue[0].id, 1); assert.equal(queue.at(-1).id, 200);
  assert.deepEqual(await (await call('/words')).json(), { words: ['alpha', 'zeta'] });
});
