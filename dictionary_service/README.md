# Moderated shared dictionary

This is a new, standalone service implementation, **not a deployed service**. The existing desktop bug-report client points to a Cloudflare Worker in `src/common/report_config.py`; this repository contains neither that backend nor an admin API. Its address is not reused or assumed to implement dictionary endpoints.

Users right-click a **TYPOS** error marker and choose “Propose a correct word”. The error detail tooltip explains this action. The dialog starts empty and submits only the explicitly entered word, never the finding, surrounding text, thesis, path, or logs. A successful submission reports pending, already approved, or previously rejected status. It does not immediately suppress an error.

## Administrator application mode

Start the desktop executable with `--dictionary-admin`, or from source run `python src/app/main.py --dictionary-admin`. This opens a dedicated Qt moderation window without starting analysis or downloading models. Set `DIPLOMACHECKER_DICTIONARY_URL=https://dictionary.example.org` in its environment first. Enter the server-configured administrator username and password in the window; no credentials are packaged, persisted, or sent in CLI arguments. Sign in / refresh loads the oldest 200 pending requests. Select a word and approve or reject it; the queue reloads after the decision. Refresh to process the next batch. Login, queue loading, and moderation use worker threads, keeping the GUI responsive. Closing during an active request is deferred until it finishes. After an uncertain connection failure, refresh before retrying a decision.

This mode needs a configured and deployed API to receive requests. Launching it alone does not provision an admin account or make a service available. An optional browser interface is also available at `/admin` after deployment, protected by the same HTTP Basic authentication. Use HTTPS for both interfaces.

## Deployment configuration still required

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

Configure `DIPLOMACHECKER_DICTIONARY_URL` in **each client/admin app environment** to the deployed HTTPS origin. It is intentionally unset by default. No deployed URL or credentials are shipped in this PR. A service placed under a URL prefix needs the proxy to strip that prefix; the optional web UI assumes the origin root.

## Synchronization and API

Before each linguistic analysis, on the analysis worker, clients fetch the full approved word list and atomically replace `approved_dictionary.json` in the app data directory. An unavailable service retains the last valid approved cache. Newly approved words affect subsequent analyses; existing findings are not rewritten. Matching uses NFC normalization and case folding and accepts only the approved word itself, not arbitrary stems. Shared words extend `is_known_word` and do not disable grammar, typography, numbering, or other checks. No GPU is used by this feature.

- `POST /proposals`: JSON containing only `word`; returns `201` with `id` and `status`. Invalid or contextual payloads are rejected.
- `GET /words`: public JSON `words` containing only approved entries.
- `GET /admin/queue`: Basic-authenticated pending requests, oldest first, up to 200.
- `POST /admin/review`: Basic authentication, `X-Dictionary-Review: 1`, JSON `id` and `decision` (`approved` or `rejected`). Atomic pending-only transitions; repeated/conflicting decisions return `409`.

The desktop application has no admin credential embedded. The custom review header and absence of CORS block cross-origin form moderation in the optional browser interface. HTTPS termination, persistent storage, supervisor, proxy limits, account provisioning, backups, and distributing the configured client URL remain operator responsibilities and have not been deployed here.
