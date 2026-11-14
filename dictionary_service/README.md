# Moderated shared dictionary

The production dictionary API is deployed on Cloudflare Workers with D1:
`https://diploma-checker-dictionary.diplomachecker.workers.dev`.
It is separate from the existing bug-report service. Thesis analysis stays local;
this service receives voluntarily submitted words and connection metadata only.

Users right-click a **TYPOS** error marker and choose “Propose a correct word”. The error detail tooltip explains this action. The dialog starts empty, shows the recipient service, and requires an unchecked-by-default voluntary submission checkbox before enabling Send. It explains that the service sees connection metadata (such as an IP address), that approved words are shared with other users, and that thesis analysis stays local. Closing the dialog or leaving the checkbox unchecked sends nothing. It submits only the explicitly entered word, never the finding, surrounding text, thesis, path, or logs. A successful submission reports pending, already approved, or previously rejected status. It does not immediately suppress an error.

## Administrator application mode

Start the desktop executable with `--dictionary-admin`, or from source run `python src/app/main.py --dictionary-admin`. This opens a dedicated Qt moderation window without starting analysis or downloading models. The application uses the deployed service by default. `DIPLOMACHECKER_DICTIONARY_URL` can override it; an explicit empty value disables remote dictionary access. Enter the server-configured administrator username and password in the window; no credentials are packaged, persisted, or sent in CLI arguments. Sign in / refresh loads the oldest 200 pending requests. Select a word and approve or reject it; the queue reloads after the decision. Refresh to process the next batch. Login, queue loading, and moderation use worker threads, keeping the GUI responsive. Closing during an active request is deferred until it finishes. After an uncertain connection failure, refresh before retrying a decision.

The Cloudflare service uses the dedicated native administrator window. It has no browser admin page. Use the administrator credentials provisioned by the deployment owner. They are not included in the app or this repository. The optional Python fallback has its own browser interface and credentials.

## Cloudflare deployment

See [Cloudflare setup and operations](cloudflare/README.md) for the Worker, D1 schema, authentication and deployment commands. The native desktop mode is the production moderation interface.

## Alternative self-hosted Python backend

The service uses Python's standard library and SQLite. Deploy it separately from the desktop app, with a persistent writable SQLite volume and an HTTPS reverse proxy. Bind the Python process to loopback or a private container interface, never expose its plain HTTP port publicly. Configure request/connection limits at the proxy, including stricter limits on administrator authentication; the built-in threaded server is intended to sit behind that proxy. Public proposal submissions are anonymous and limited to 30 per connecting address per UTC day. Behind a proxy this is the proxy address: configure public client rate limits there; the service deliberately does not trust forwarded address headers. No CORS access is enabled.

Generate a random admin password and derive its scrypt hash interactively on the server:

```sh
python3 - <<'PY'
import getpass, hashlib, secrets
salt = secrets.token_bytes(16)
password = getpass.getpass('Administrator password: ')
print('DICTIONARY_ADMIN_SALT=' + salt.hex())
print('DICTIONARY_ADMIN_HASH=' + hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex())
PY
```

Supply these through your deployment's protected environment configuration:

- `DICTIONARY_ADMIN_USER`: administrator username.
- `DICTIONARY_ADMIN_SALT` and `DICTIONARY_ADMIN_HASH`: generated values above (no plaintext server password).
- `DICTIONARY_DB`: persistent SQLite file path, e.g. `/var/lib/dictionary/dictionary.sqlite3`.
- `DICTIONARY_BIND`: defaults to `127.0.0.1`.
- `PORT`: defaults to `8080`.

Run `python3 -m dictionary_service.server` from the repository root under a supervised service account. Back up the database using SQLite's backup API; preserve its volume across process/container upgrades. Review records retain decision, timestamp, and administrator identity. Decisions are final through the API; duplicate words reuse their existing status. Credentials can be rotated by changing the deployment environment and restarting. Multiple instances require a shared SQLite-safe filesystem or a future database adaptation; do not put independent databases behind a load balancer.

To use this alternative backend, override `DIPLOMACHECKER_DICTIONARY_URL` in each client/admin app environment with its HTTPS origin. Otherwise clients use the Cloudflare service. No credentials are shipped in the application. A service placed under a URL prefix needs the proxy to strip that prefix; the optional web UI assumes the origin root.

## Synchronization and API

Before each linguistic analysis, on the analysis worker, clients fetch the full approved word list and atomically replace `approved_dictionary.json` in the app data directory. An unavailable service retains the last valid approved cache. Newly approved words affect subsequent analyses; existing findings are not rewritten. Matching uses NFC normalization and case folding and accepts only the approved word itself, not arbitrary stems. Shared words extend `is_known_word` and do not disable grammar, typography, numbering, or other checks. No GPU is used by this feature.

- `POST /proposals`: JSON containing only `word`; returns `201` with `id` and `status`. Invalid or contextual payloads are rejected.
- `GET /words`: public JSON `words` containing only approved entries.
- `GET /admin/queue`: Basic-authenticated pending requests, oldest first, up to 200.
- `POST /admin/review`: Basic authentication, `X-Dictionary-Review: 1`, JSON `id` and `decision` (`approved` or `rejected`). Atomic pending-only transitions; repeated/conflicting decisions return `409`.

The desktop application has no admin credential embedded. The custom review header and absence of CORS block cross-origin form moderation in the optional browser interface. For this Python fallback, HTTPS termination, persistent storage, supervisor, proxy limits, account provisioning and backups remain operator responsibilities. This fallback has not been deployed; the Cloudflare service is the production deployment.

## Opening the administrator window from this checkout (Linux)

With the existing development Python environment, no rebuild or GPU is needed:

```sh
cd /path/to/app
python src/app/main.py --dictionary-admin
```

The built-in Cloudflare address is used automatically. For an alternative
installation, set its actual HTTPS address in the same terminal before launching:

```sh
export DIPLOMACHECKER_DICTIONARY_URL="https://YOUR-DICTIONARY-HOST"
python src/app/main.py --dictionary-admin
```

Use the administrator credentials configured on the service, not a GitHub or
Gmail password. Click **Sign in / refresh queue**, select a word, then **Approve**
or **Reject**. Ordinary users never need these credentials. A future packaged
application containing this PR supports `./DiplomaChecker --dictionary-admin`.
The currently installed older application may not contain that command yet.
