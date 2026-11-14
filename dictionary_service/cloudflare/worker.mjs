import casefold from './casefold.mjs';
const encoder = new TextEncoder();
const letter = /^\p{L}$/u;
class HttpError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
export function normalizeWord(value) {
  if (typeof value !== 'string') throw new HttpError(400, 'Word must be text');
  // Python str.strip excludes BOM, unlike JS \s.
  const whitespace = /^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]+$/gu;
  const word = [...value.normalize('NFC').replace(whitespace, '')]
    .map(c => casefold[c] ?? c.toLowerCase()).join('');
  const chars = [...word];
  if (!chars.length || chars.length > 80 || !letter.test(chars[0]) || !letter.test(chars.at(-1)) ||
      !chars.every(c => letter.test(c) || "-'’".includes(c))) {
    throw new HttpError(400, 'Enter one word (up to 80 letters)');
  }
  return word;
}
function reply(status, data, extra = {}) {
  return new Response(status === 401 ? null : JSON.stringify(data), { status, headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'none'; frame-ancestors 'none'", ...extra,
  }});
}
function hex(value, bytes) {
  if (typeof value !== 'string' || !new RegExp(`^[a-fA-F0-9]{${bytes * 2}}$`).test(value)) throw new Error('Configuration');
  return Uint8Array.from(value.match(/../g), x => parseInt(x, 16));
}
function equal(a, b) {
  let diff = a.length ^ b.length;
  for (let i = 0; i < Math.max(a.length, b.length); i++) diff |= (a[i] ?? 0) ^ (b[i] ?? 0);
  return diff === 0;
}
async function authenticated(request, env) {
  const auth = request.headers.get('Authorization') ?? '';
  if (auth.length > 4096 || !auth.startsWith('Basic ')) return false;
  let user, password;
  try {
    const token = auth.slice(6);
    if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(token)) return false;
    const decoded = new TextDecoder('utf-8', { fatal: true }).decode(Uint8Array.from(atob(token), c => c.charCodeAt(0)));
    const colon = decoded.indexOf(':');
    if (colon < 0) return false;
    user = decoded.slice(0, colon); password = decoded.slice(colon + 1);
  } catch { return false; }
  if (!env.DICTIONARY_ADMIN_USER || !equal(encoder.encode(user), encoder.encode(env.DICTIONARY_ADMIN_USER))) return false;
  const salt = hex(env.DICTIONARY_ADMIN_SALT, 16);
  const expected = hex(env.DICTIONARY_ADMIN_HASH, 32);
  const key = await crypto.subtle.importKey('raw', encoder.encode(password), 'PBKDF2', false, ['deriveBits']);
  const hash = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 100000 }, key, 256);
  return equal(new Uint8Array(hash), expected);
}
async function readJson(request) {
  const declared = request.headers.get('Content-Length');
  if (declared !== null && (!/^\d+$/.test(declared) || +declared < 1 || +declared > 1024)) throw new HttpError(413, 'Invalid request size');
  if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') throw new HttpError(415, 'JSON required');
  if (!request.body) throw new HttpError(413, 'Invalid request size');
  const reader = request.body.getReader();
  const chunks = []; let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 1024) { await reader.cancel(); throw new HttpError(413, 'Invalid request size'); }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  if (!size || (declared !== null && +declared !== size)) throw new HttpError(413, 'Invalid request size');
  const bytes = new Uint8Array(size); let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
  let data;
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); }
  catch { throw new HttpError(400, 'Invalid JSON'); }
  if (!data || Array.isArray(data) || typeof data !== 'object') throw new HttpError(400, 'Object required');
  return data;
}
async function propose(request, env, word) {
  // Only Cloudflare's edge-controlled address; never trust X-Forwarded-For.
  const ip = request.headers.get('CF-Connecting-IP');
  if (!ip) throw new HttpError(503, 'Client address unavailable');
  const key = await crypto.subtle.importKey('raw', hex(env.RATE_LIMIT_SALT, 32), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const digest = await crypto.subtle.sign('HMAC', key, encoder.encode(ip));
  const address = [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
  const day = new Date().toISOString().slice(0, 10);
  const sql = (query, ...args) => env.DB.prepare(query).bind(...args);
  const results = await env.DB.batch([
    sql("DELETE FROM rate_limits WHERE day < date(?, '-2 days')", day),
    sql('INSERT INTO rate_limits(address,day,count) VALUES(?,?,1) ON CONFLICT(address,day) DO UPDATE SET count=MIN(count+1,31) RETURNING count', address, day),
    sql("INSERT INTO proposals(word) SELECT ? WHERE (SELECT count FROM rate_limits WHERE address=? AND day=?) <= 30 ON CONFLICT(word) DO NOTHING", word, address, day),
    sql('SELECT id,status FROM proposals WHERE word=? AND (SELECT count FROM rate_limits WHERE address=? AND day=?) <= 30', word, address, day),
  ]);
  if (results[1].results[0].count > 30) throw new HttpError(429, 'Daily proposal limit reached');
  return reply(201, results[3].results[0]);
}
export default {
  async fetch(request, env) {
    try {
      const path = new URL(request.url).pathname;
      if (path === '/admin' || path.startsWith('/admin/') || path === '/admin.js') {
        if (!await authenticated(request, env)) return reply(401, null, { 'WWW-Authenticate': 'Basic realm="Dictionary review", charset="UTF-8"' });
      }
      if (request.method === 'GET' && path === '/words') {
        const rows = await env.DB.prepare("SELECT word FROM proposals WHERE status='approved' ORDER BY word").all();
        return reply(200, { words: rows.results.map(r => r.word) });
      }
      if (request.method === 'GET' && path === '/admin/queue') {
        const rows = await env.DB.prepare("SELECT * FROM proposals WHERE status='pending' ORDER BY id LIMIT 200").all();
        return reply(200, rows.results);
      }
      if (request.method !== 'POST' || !['/proposals', '/admin/review'].includes(path)) return reply(404, { error: 'Not found' });
      if (path === '/admin/review' && request.headers.get('X-Dictionary-Review') !== '1') throw new HttpError(403, 'Missing review header');
      const data = await readJson(request);
      if (path === '/proposals') {
        if (Object.keys(data).length !== 1 || !Object.hasOwn(data, 'word')) throw new HttpError(400, 'Only a word is accepted; do not send document context');
        return await propose(request, env, normalizeWord(data.word));
      }
      if (Object.keys(data).length !== 2 || !Object.hasOwn(data, 'id') || !Number.isSafeInteger(data.id) || !['approved', 'rejected'].includes(data.decision)) throw new HttpError(400, 'Invalid review');
      const result = await env.DB.prepare("UPDATE proposals SET status=?,reviewed=CURRENT_TIMESTAMP,reviewer=? WHERE id=? AND status='pending'")
        .bind(data.decision, env.DICTIONARY_ADMIN_USER, data.id).run();
      if (result.meta.changes !== 1) throw new HttpError(409, 'Proposal missing or already reviewed');
      return reply(200, { status: data.decision });
    } catch (error) {
      // Never log request bodies, headers, submitted words, credentials, or DB exceptions.
      return reply(error instanceof HttpError ? error.status : 500, { error: error instanceof HttpError ? error.message : 'Internal server error' });
    }
  },
};
