# Cloudflare dictionary backend

Dependency-free Worker implementing the native dictionary API from `../server.py`.
The Python service remains an independent reference/fallback. This Worker has no
browser admin page: use the desktop `--dictionary-admin` window.

The configured Worker origin is
`https://diploma-checker-dictionary.diplomachecker.workers.dev`.
The service was deployed and verified on 14 November 2026. Production checks covered proposal validation, unauthenticated access rejection, administrator login, approval, rejection, and approved-word publication. Synthetic production records were removed after verification.

## Provision and deploy

Run commands from this directory with an authenticated Wrangler CLI. The Worker
name and D1 database name are `diploma-checker-dictionary`; `wrangler.toml` binds
`DB` to database `31afb11b-ca1e-4eb1-90ea-804b9d0c314f` in account
`c33f9d914f83e60050e14e44fd6b8b16`. The database was provisioned in EEUR.

```sh
# Local schema and runtime smoke test (no remote writes):
npx wrangler d1 execute diploma-checker-dictionary --local --file schema.sql
npx wrangler dev

# Operator deployment steps:
npx wrangler d1 execute diploma-checker-dictionary --remote --file schema.sql
npx wrangler deploy --secrets-file /secure/path/dictionary-secrets.json
```

Use a protected JSON secrets file with these keys; never commit it:

- `DICTIONARY_ADMIN_USER`: `praha6248` (username is not an authentication secret).
- `DICTIONARY_ADMIN_SALT`: exactly 16 random bytes, hex encoded (32 hex characters).
- `DICTIONARY_ADMIN_HASH`: exactly 32 bytes, hex encoded (64 hex characters),
  derived using PBKDF2-HMAC-SHA256, **100000 iterations**, UTF-8 password bytes.
- `RATE_LIMIT_SALT`: exactly 32 random bytes, hex encoded (64 hex characters).

The parent deployment owner generates and installs credentials. For an independent
installation, this interactive Python recipe produces compatible values without
printing or taking the plaintext password as a command argument:

```sh
python3 - <<'PY'
import getpass, hashlib, json, secrets
password = getpass.getpass('Administrator password: ')
salt = secrets.token_bytes(16)
print(json.dumps({
    'DICTIONARY_ADMIN_USER': 'praha6248',
    'DICTIONARY_ADMIN_SALT': salt.hex(),
    'DICTIONARY_ADMIN_HASH': hashlib.pbkdf2_hmac(
        'sha256', password.encode('utf-8'), salt, 100000, dklen=32).hex(),
    'RATE_LIMIT_SALT': secrets.token_hex(32),
}, indent=2))
PY
```

Redirect generated JSON into a protected file if provisioning it; avoid terminal
capture or CI logs containing the generated secrets. Rotate admin salt/hash
jointly. The Python fallback uses scrypt and cannot reuse this PBKDF2 hash.
WebCrypto handles PBKDF2 asynchronously; only admin requests with a syntactically
valid Basic header and matching username derive a password hash. Verify successful
and unsuccessful authenticated requests against the actual Worker plan's CPU
budget before relying on production moderation. Apply edge authentication abuse
limits as appropriate for the deployment.

## API and storage

- `GET /words` returns `{"words":[...]}` containing approved entries only.
- `POST /proposals` accepts exactly `{"word":"..."}` and returns HTTP 201 with
  `{"id":1,"status":"pending"}` (duplicates return their existing ID/status).
- `GET /admin/queue` requires UTF-8 Basic authentication and returns the oldest
  200 pending proposal rows, including timestamps and reviewer fields.
- `POST /admin/review` additionally requires `X-Dictionary-Review: 1` and exactly
  `{"id":1,"decision":"approved"}` or `rejected`. Only pending records change;
  missing/already reviewed IDs return 409. Every unauthenticated admin path
  returns 401, including unsupported methods and unknown admin subpaths.

Words follow Python NFC/strip/casefold semantics, then Unicode letter validation
with internal ASCII hyphens, ASCII apostrophes, or right apostrophes. Both ends
must be letters and the normalized result must contain 1–80 Unicode codepoints.
`casefold.mjs` contains generated Python Unicode 14 casefold exceptions; each
remaining codepoint is lowercased independently to avoid JS contextual final-sigma
behavior. Unicode letter recognition follows the deployed JS runtime version.

JSON request bodies are limited to 1024 actual UTF-8 bytes, including streamed
bodies without Content-Length; a supplied length must also be valid and match.
Responses disable caching and sniffing, deny framing and provide restrictive CSP.
There are no CORS headers, browser scripts, or public moderation pages.

The proposal batch atomically cleans stale counters, increments a counter with
`RETURNING`, conditionally inserts only for counts <=30, and reads the existing
proposal. Overflow counters saturate at 31 and cannot admit later requests that
day. Duplicate submissions also consume budget. UTC date is fixed per request.
Counters retain the current day and two preceding days; older rows are cleaned
on the next valid proposal. Addresses are HMAC-SHA256 hashes keyed by
`RATE_LIMIT_SALT`; the Worker only uses Cloudflare's `CF-Connecting-IP`, never
X-Forwarded-For. Local smoke tests must explicitly supply CF-Connecting-IP;
missing addresses fail closed with 503. Changing the rate-limit secret resets
address identity and therefore effective budgets.

Review is one conditional UPDATE, so concurrent decisions cannot both succeed.
The Worker emits no console logs or request payloads, and observability is disabled
in Wrangler. Database failures return a generic message. Cloudflare may retain
platform connection metadata according to account settings; D1 intentionally
retains submitted words and review records.

D1 batch transaction behavior is documented in the
[Cloudflare D1 API](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch);
cryptographic operations use [Workers WebCrypto](https://developers.cloudflare.com/workers/runtime-apis/web-crypto/).

## Tests and migration

```sh
npm test
```

Node >=22.13 is required for built-in `node:sqlite` (some Node versions emit its
experimental warning). No npm dependencies or installation step are required.
Tests call the real Worker fetch handler through a D1-shaped adapter executing
the real SQL/schema in SQLite transactions. They cover UTF-8 Basic auth, native
client payloads, normalization, moderation races, duplicate races, the daily
30-request boundary, keyed address hashes, cleanup, body/content limits, safe
errors, and transaction rollback. They do not emulate Cloudflare CPU accounting
or network-level scheduling; Wrangler local and production smoke tests supplement
them. The deployment owner has separately verified local Wrangler propose/auth/
approve/words behavior and dry-run packaging.

`schema.sql` is idempotent for fresh installs and repeat application; it is not an
upgrade framework for arbitrary preexisting schemas. Its tables match the Python
reference, with added indexes and constraints on new databases. To migrate existing
reference data, stop writes, back up SQLite with SQLite's backup API, export and
import only `proposals` (preserving IDs, words, status, timestamps and reviewer),
then verify row counts and approved words before switching clients. Do not import
Python's unkeyed IP hashes or scrypt credentials. D1 has independent backups/export
facilities; keep a verified backup before schema/data changes. Future schema
changes should use versioned Wrangler migrations reviewed before application.
