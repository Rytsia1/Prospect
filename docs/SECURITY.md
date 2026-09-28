# Prospect Security Model

Prospect handles untrusted input: uploaded PDFs, filenames, request parameters, headers and
anything the browser sends. Documents, extracted evidence, financial facts, exports and signed
storage URLs are treated as sensitive. Every control below is enforced by the API or the worker;
the web client only mirrors some of them for a better message.

## 1. Threats covered

| Area | Control | Where |
|---|---|---|
| API abuse | Server-side rate limits, 429 + `Retry-After` | `app/ratelimit.py`, `app/auth.py` |
| Token theft/replay | Signed, expiring, revocable sessions in an HttpOnly cookie | `app/auth.py` |
| CSRF | SameSite=Strict + trusted Origin/Referer + per-session CSRF token | `app/auth.py`, `app/main.py` |
| XSS impact | Nonce CSP, no inline/third-party scripts, no HTML sinks | `apps/web/middleware.ts`, `lib/csp.ts` |
| Clickjacking, sniffing, leaks | Security headers on API and pages | `app/main.py`, `apps/web/next.config.ts` |
| Cross-origin reads | Exact-origin CORS, no credentials, restricted methods/headers | `app/main.py` |
| Oversized uploads | Size signed into the storage URL; re-checked on completion | `app/storage.py`, `app/documents.py` |
| Tampered uploads | SHA-256 signed into the upload, compared on completion, re-hashed by the worker | same + `app/worker.py` |
| Malicious PDFs | Threat scan, then parsing in a killable child process with limits | `app/scanning.py`, `app/sandbox.py` |
| Retry amplification | Document failures never retried; infra retries bounded with backoff | `app/worker.py` |
| Unbounded reads/exports | Paging, SQL-side counts, company-scope cap, export caps | `app/documents.py`, `app/financials.py` |
| Resource exhaustion | Per-user document, storage and processing quotas (race-safe) | `app/quotas.py` |
| Data lingering | Deletion endpoint, retention sweep, storage lifecycle rules | `app/documents.py`, `app/worker.py`, `app/storage.py` |
| Repudiation | Append-only, per-user audit trail of sensitive operations | `app/logs.py` (`audit_event`) |
| Supply chain | Pinned actions, least-privilege CI, dependency and secret scanning | `.github/workflows/ci.yml` |

**Limit of the parser sandbox.** The child process is a resource boundary (time, memory), not a
code-execution boundary: it inherits the worker's environment variables and returns its result
by pickle over a pipe. A PyMuPDF memory-corruption exploit in the child would reach the worker's
credentials. Stronger isolation needs a separate container without database or storage secrets
(e.g. a parse-only service, gVisor/Firecracker).

Unchanged protections: every document query is scoped by `document.user_id == <session user>`
(`_owned_document`); SQL is built with SQLAlchemy (parameterized); storage keys are random, never
derived from filenames; extracted PDF text is rendered as escaped React text (no
`dangerouslySetInnerHTML`, `innerHTML`, `eval` or `new Function` in the web app); CSV exports
escape spreadsheet formulas.

## 2. Anonymous sessions, cookies and CSRF

There are no accounts yet. `POST /api/v1/sessions` creates an anonymous user and a session:

```text
v1.<session_id>.<issued_at>.<expires_at>.<HMAC-SHA256(APP_SECRET, first four fields)>
```

A request is authenticated only if the token is well formed, the signature matches, `expires_at`
is in the future, and the `sessions` row exists, is not revoked and is not expired; otherwise
`401`. The session's user id scopes every query; the client never names an owner.

**Browsers never see the token.** It is set as a cookie `__Host-prospect_session`: `HttpOnly`,
`Secure`, `SameSite=Strict`, `Path=/`, no `Domain`. It is never returned in a body, a URL or a
query string, and the web app keeps nothing in `localStorage`: a pre-P1 token found there is
removed on load and traded once (Bearer `POST /sessions/refresh`) for a cookie session of the same
user, which also revokes it, so earlier uploads stay reachable. The browser calls the web app's own `/api/v1/*`, which Next.js proxies to the API
(`apps/web/next.config.ts`), so the cookie is first-party and `SameSite=Strict` breaks nothing:
there is no cross-site flow that needs it.

**CSRF.** For cookie-authenticated `POST`/`PATCH`/`PUT`/`DELETE`:

1. `SameSite=Strict`: other sites cannot make the browser send the cookie at all;
2. the `Origin` header (or, without it, the `Referer`'s origin) must be one of `ALLOWED_ORIGINS`.
   A request with neither, or with `Origin: null`, is refused;
3. the `X-CSRF-Token` header must equal `HMAC-SHA256(APP_SECRET, "csrf." + session_id)`, compared
   in constant time. The page gets it from `POST /sessions`, `POST /sessions/refresh` or
   `GET /sessions/current` (readable only same-origin); it changes with every session.

Any state-changing request whose `Origin` is present and untrusted is refused before routing,
which also blocks login CSRF on `POST /sessions`. Failures are `403 csrf_failed` and a
`csrf_rejected` security event. Non-browser clients may send `Authorization: Bearer <token>`
(taken from the `Set-Cookie`); a browser never attaches that header by itself, so Bearer requests
need no CSRF token.

| Endpoint | Purpose |
|---|---|
| `POST /sessions` | new anonymous user + session cookie (rate limited per client IP) |
| `GET /sessions/current` | the session's times and CSRF token |
| `POST /sessions/refresh` | new session for the same user; the old one is revoked |
| `DELETE /sessions/current` | revoke the session now and clear the cookie (sign out) |

**Workspace lifecycle.** Anonymous sessions are a product decision (no sign-up); the workspace
is temporary and private, and never outlives the ability to reach it:

| Stage | Rule | Setting (default) |
|---|---|---|
| Session in use | refreshed by the web client past half-life (same user, same documents) | `SESSION_TTL_SECONDS` (24 h) |
| Session ends | expired, or revoked by sign-out: every request is `401`, the workspace is unreachable | — |
| Workspace deleted | no usable session for the grace period: files, then the user row and everything it owns (documents, derived data, companies, scenarios, audit rows) | `WORKSPACE_GRACE_HOURS` (24) |
| Document retention | every document is deleted this long after upload, even in a live workspace; required in production | `DOCUMENT_RETENTION_DAYS` (30) |
| Failed uploads | file deleted within minutes; record after | `FAILED_DOCUMENT_RETENTION_HOURS` (24) |
| Exports | never stored (built per request) | no `EXPORT_RETENTION_HOURS` needed |

Session expiry and document deletion are distinct: expiry only cuts access; deletion follows
after the grace period (or retention), so an expired session never leaves sensitive files behind
indefinitely. **Limitations:** identity is the cookie. Clearing cookies, another browser, or a
session left unused past its TTL loses the workspace for good: there is no recovery by design (no
account, no email), and anyone holding the device's cookie is the user. Rotating `APP_SECRET`
ends every session (and so, after the grace period, every workspace).

## 3. Uploads: integrity is not type validation

*Content integrity* answers "are these exactly the bytes the user declared?" (length and
SHA-256). *File type validation* answers "is this a PDF we can safely parse?". Passing one says
nothing about the other: a perfectly intact file can be malicious, and a real PDF can arrive
truncated. Prospect checks both, in this order:

1. `POST /documents` validates the declared type, size (`MAX_UPLOAD_BYTES`, 50 MiB) and SHA-256,
   checks quotas, and returns a presigned PUT URL for one random key under `uploads/`. The
   signature covers `Content-Length`, `Content-Type: application/pdf` and
   `x-amz-checksum-sha256`: storage refuses any other length or type, and S3/R2 refuse a body
   whose SHA-256 differs from the signed one. The URL allows only `PUT` to exactly that key, for
   `SIGNED_URL_TTL_SECONDS` (15 min).
2. `POST /documents/{id}/complete` re-reads the stored object: it must exist, its size must equal
   the declared size, the SHA-256 recorded by storage (when the provider records one) must match,
   the stored type must be `application/pdf`, and the first KiB must contain `%PDF-`. Otherwise
   the object is deleted and the document is `FAILED`. A verified object is copied to
   `documents/` (server-side) and the `uploads/` copy removed.
3. The worker downloads the file and checks again, independently of storage: size, SHA-256
   (hashing the bytes itself), PDF signature. Then the threat scan (§4), then the parser opens it
   in the sandbox (PDF only: PyMuPDF may not treat it as XPS/EPUB/image), requires pages, no
   password, and every limit (§5). Parser errors become fixed messages; raw exceptions never reach
   clients.

Filenames are display text only: NFKC-normalized, last path component, control and format
characters (NUL, bidi overrides) removed, at most 255 characters, rendered escaped by React.
Storage keys are always random.

Signed URLs: upload and download URLs expire after `SIGNED_URL_TTL_SECONDS`, are returned only to
the document's owner, are never stored, never logged (no access log, no URL in log fields) and
never put in error messages. A download URL grants `GET` on one object only.

## 4. Threat scanning

`DOCUMENT_SCANNER` chooses the scanner (`app/scanning.py`, a `DocumentScanner` protocol):

| Value | Behaviour |
|---|---|
| `clamav` | Each PDF is streamed to clamd (`CLAMAV_HOST`, `CLAMAV_PORT`, INSTREAM) before parsing. `FOUND` → document `FAILED` ("rejected by the security scan"), never retried, never parsed. |
| `none` | No scan; the document is recorded as `threat_scan = "not_scanned"`. |
| unset | Allowed in development (behaves as `none`); **production refuses to start**. |

**Policy when the scanner is unavailable:** fail closed. A scanner error, timeout, size-limit
error or unexpected reply raises `ScannerUnavailable`; the job is retried with backoff up to
`PROCESSING_MAX_ATTEMPTS`, then the document is `FAILED`. It is never parsed and never marked
clean. `threat_scan` is `clean` only after a clean clamd verdict; the API returns it with each
document.

**Limitations:** signature scanning catches known malware, not novel PDF exploits (the sandbox and
limits are the defence there). clamd's `StreamMaxLength` must be at least `MAX_UPLOAD_BYTES`, or
large files fail closed. Running clamd (a separate service with signature updates) is a
deployment task.

## 5. Processing limits

The worker downloads the PDF to a temporary directory (deleted after every attempt), then runs
`app/pipeline.analyze` in a fresh child process (`multiprocessing` spawn). The parent waits at
most `PROCESSING_TIMEOUT_SECONDS` and kills the child. On Linux the child also has an address-space
cap (`PROCESSING_MAX_MEMORY_BYTES`, `RLIMIT_AS`). The API process never parses PDFs.

| Setting | Default | Exceeded → |
|---|---|---|
| `PROCESSING_MAX_PAGES` | 2000 | document FAILED |
| `PROCESSING_TIMEOUT_SECONDS` | 120 | child killed, FAILED |
| `PROCESSING_MAX_MEMORY_BYTES` | 2 GiB | child dies, FAILED (Linux) |
| `PROCESSING_MAX_TEXT_BYTES` | 50,000,000 | FAILED |
| `PROCESSING_MAX_TABLE_CELLS` | 500,000 | FAILED (checked before cells are read) |
| `PROCESSING_MAX_FACTS` / `PROCESSING_MAX_EVIDENCE` | 5,000 | FAILED (never a truncated subset) |
| `PROCESSING_MAX_ROW_CHARS` | 2,000 | row ignored as evidence |

**Retries.** Failures caused by the document (unreadable, over a limit, timeout, crash, checksum,
infected) are permanent. Infrastructure errors (storage, database, scanner) are retried up to
`PROCESSING_MAX_ATTEMPTS` (3) after `PROCESSING_RETRY_BASE_SECONDS × 2^(n−1)` plus up to 50%
jitter. A job whose worker died is reclaimed after `PROCESSING_LEASE_SECONDS` and counts as an
attempt.

## 6. Quotas (per user)

| Setting | Default | Counted |
|---|---|---|
| `QUOTA_MAX_DOCUMENTS` | 100 | documents not FAILED |
| `QUOTA_MAX_STORAGE_BYTES` | 2 GiB | bytes stored or reserved by in-progress uploads |
| `QUOTA_MAX_ACTIVE_JOBS` | 3 | queued + running jobs |
| `QUOTA_MAX_DAILY_JOBS` | 50 | jobs created in the last 24 h |

Checks lock the user's row (`SELECT … FOR NO KEY UPDATE`) in the same transaction as the insert,
so parallel requests cannot both pass on the last slot (while audit rows referencing the user can
still be written). Document/storage quota → `409 quota_exceeded`; processing quota → `429`.
Deleting a document frees its quota.

## 7. Rate limits

Fixed windows counted in PostgreSQL (shared by all API instances; one atomic upsert per request).
Format `<requests>/<window seconds>`. Anonymous endpoints count per client IP; authenticated ones
per user.

| Setting | Default | Endpoints |
|---|---|---|
| `RATE_LIMIT_SESSIONS` | 5/60 per IP | `POST /sessions` |
| `RATE_LIMIT_SESSION_REFRESH` | 10/3600 | `POST /sessions/refresh` |
| `RATE_LIMIT_UPLOADS` | 20/3600 | `POST /documents` |
| `RATE_LIMIT_COMPLETE` | 30/3600 | `POST /documents/{id}/complete` |
| `RATE_LIMIT_FINANCIALS` | 60/60 | `GET /documents/{id}/financials` |
| `RATE_LIMIT_COMPUTE` | 30/60 | diff, scenario preview, data quality |
| `RATE_LIMIT_EXPORT` | 10/60 | `GET /documents/{id}/export` |
| `RATE_LIMIT_SESSIONS_DAILY` | 50/86400 per IP | `POST /sessions` |
| `RATE_LIMIT_UPLOADS_IP` | 60/3600 per IP | `POST /documents` |
| `RATE_LIMIT_COMPLETE_IP` | 90/3600 per IP | `POST /documents/{id}/complete` |
| `RATE_LIMIT_EXPORT_IP` | 30/60 per IP | `GET /documents/{id}/export` |

**Abuse through new sessions.** A new anonymous session is a new user with fresh per-user quotas,
so the expensive paths are also limited per client IP (above), session creation per IP per
minute and per day, and processing by a global cap on queued + running jobs
(`QUOTA_MAX_QUEUED_JOBS`, 500; `503` when full). Opening sessions does not reset any of them.
No fingerprinting or tracking is used: the only identifiers are the session and the IP.

**Client IP (trust boundary).** Browser → Vercel (Next.js) → API. Vercel's edge overwrites
`X-Forwarded-For`/`X-Real-IP` with the visitor's address, so the web app's proxy
(`apps/web/middleware.ts`) reads it there, drops any `X-Prospect-*` header the browser sent, and
forwards the IP as `X-Prospect-Client-IP` together with `TRUSTED_PROXY_SECRET`. The API
(`app/ratelimit.client_ip`) believes that header only with the secret (constant-time compare)
and only if it parses as an IP address. Every other request, including one sent straight to the
API with forged `X-Forwarded-For`, `X-Real-IP`, `Forwarded` or `X-Prospect-Client-IP`, is counted
by its TCP peer address. Uvicorn runs with `--no-proxy-headers`, so it never rewrites the peer
from `X-Forwarded-For` either; `FORWARDED_ALLOW_IPS` is not used. Outside Vercel (`next start`)
the web proxy forwards no IP, because there the forwarding headers come from the client.

## 8. Financial data, queries and exports

- `GET /documents/{id}/metrics` is paged in SQL: `limit` (default 100, at most 500) and `offset`.
- Any unpaged load of facts counts rows in SQL first and refuses more than `FINANCIALS_MAX_FACTS`
  (10,000) with `413 financial_data_too_large`; page text is never loaded to build fact lists.
- Company scope is capped at `FINANCIALS_MAX_DOCUMENTS` (20) reports and never crosses owners:
  the query filters by the session's user first. A document linked to a company workspace groups
  by that company's id only; an unlinked one groups by its exact normalized label among unlinked
  documents ("Acme" and "Acme Inc." stay separate). Relabeling a document unlinks it.
- Exports are rate limited; more than `EXPORT_MAX_RECORDS` (20,000) rows or `EXPORT_MAX_BYTES`
  (20 MiB) → `413 export_too_large`, never a silently shortened file. Exports are built in memory
  and never stored, so there is no export artifact to retain or delete.
- **Query parameters:** every parameter is typed and bounded (limits, UUIDs, enumerated values
  such as `scope`, `format`, review `status`, lengths of free-text filters). There are no sort
  parameters and no regex/LIKE search. Unknown query parameters are `400 unknown_parameter`,
  never silently ignored (this caught the review page's default filter being ignored). SQL is
  parameterized; no identifier is built from input.

## 9. Deletion, retention and storage lifecycle

`DELETE /documents/{id}` (owner only; another user's id is `404`) deletes the stored file first,
then the database row, whose pages, sections, chunks, evidence, facts, calculations, jobs,
reviews, quality issues, comparisons and document-based scenarios cascade. Companies, watchlists
and the audit trail are kept. If storage fails, nothing changes (`503`, retry); if the database
fails afterwards, the row remains and a retry completes (deleting a missing object succeeds). A
second delete answers `404`.

The worker's `sweep` (every 5 minutes):

| What | When |
|---|---|
| Upload never completed | signed URL expired (+60 s): object deleted, document FAILED |
| FAILED document's file | next sweep |
| FAILED document's record | `FAILED_DOCUMENT_RETENTION_HOURS` (24) after it failed |
| Any document and all its data | `DOCUMENT_RETENTION_DAYS` (30) after upload |
| An unreachable workspace | `WORKSPACE_GRACE_HOURS` (24) after its last session ended (§2) |
| Rate-limit counters / sessions | once expired / 7 days after expiry |

Temporary files need no sweep: each processing attempt deletes its own directory.

**Storage lifecycle (defence in depth).** `python -m app.storage lifecycle` (run once, with
credentials allowed to configure the bucket) installs rules that expire everything under
`uploads/` after 1 day (and abort incomplete multipart uploads), and, when
`DOCUMENT_RETENTION_DAYS` is set, everything under `documents/` a day after that. They clean up
even if the API or worker crashed or never ran.

**Reconciliation** (`app/reconcile.py`; daily in the worker, or `python -m app.reconcile
[--delete]` by hand, dry run by default) compares storage with the database, conservatively:

| Finding | Action |
|---|---|
| Object under `uploads/` or `documents/` with no document row, older than `RECONCILE_ORPHAN_GRACE_HOURS` (48) | deleted, after re-checking the database for that key right before |
| Such an object inside the grace window | kept (it may belong to a request in flight) |
| Object under any other prefix | never listed, never touched |
| Document the database calls stored whose object is gone | `object_missing` event, reported for a person; the worker fails it permanently when it reads it |
| Job RUNNING past its lease | counted; the worker reclaims it |

## 10. Browser security

**Pages** (`apps/web/middleware.ts`, `lib/csp.ts`, `next.config.ts`):

```text
Content-Security-Policy: default-src 'self'; script-src 'self' 'nonce-<per request>' 'strict-dynamic';
  style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self';
  connect-src 'self' <STORAGE_ORIGIN>; object-src 'none'; frame-src 'none'; frame-ancestors 'none';
  base-uri 'self'; form-action 'self'; upgrade-insecure-requests
X-Content-Type-Options: nosniff        X-Frame-Options: DENY
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=()
Cross-Origin-Opener-Policy: same-origin
Strict-Transport-Security: max-age=31536000; includeSubDomains   (production builds)
```

Exceptions, and why: `style-src 'unsafe-inline'` (React `style` attributes on charts and progress
bars cannot carry a nonce; CSS cannot run script); `'unsafe-eval'` only under `next dev`. Pages render per request so each gets its
nonce. The app has no analytics, third-party scripts, web fonts, iframes or `postMessage`. PDFs
open in a new tab from a signed storage URL, only if it is `http(s)`, with
`noopener,noreferrer`. Blob URLs are used only for export downloads and revoked immediately.

**API responses** (`app/main.py`): `Content-Security-Policy: default-src 'none'; frame-ancestors
'none'`, `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Permissions-Policy`,
`Cross-Origin-Resource-Policy: same-origin`, `Cache-Control: no-store`, and HSTS in production.

**CORS:** `ALLOWED_ORIGINS` exactly (never `*`, never reflected), no credentials, methods
`GET POST PATCH DELETE`, headers `Authorization Content-Type X-CSRF-Token X-Request-ID`. Browsers
use the same-origin proxy, so CORS only serves Bearer clients on a trusted origin.

## 11. Logging, request ids, errors and audit trail

**Request ids.** A client `X-Request-ID` is kept only if it matches `[A-Za-z0-9._-]{1,64}`;
anything else is replaced by a UUID, so ids are safe to log and echo (no log injection).

**Logs** are JSON lines. Never logged: `Authorization` headers, cookies, session or CSRF tokens,
signed URLs, `APP_SECRET`, database or storage credentials, document text, evidence or other
financial content. The access log is off; request lines carry method, path, status and timing
only (no query strings). Database errors are logged without their bound values
(`hide_parameters`). Security events (`prospect.security`): `session_invalid`, `session_expired`,
`session_revoked`, `csrf_rejected`, `rate_limit_exceeded`, `upload_rejected_size`,
`upload_rejected_type`, `upload_checksum_mismatch`, `upload_rejected_malware`,
`threat_scan_unavailable`, `quota_exceeded`, `authorization_denied`, `processing_timeout`,
`processing_resource_limit`, `financial_data_limit_exceeded`, `export_limit_exceeded`.

**Errors.** Every error is `{"error": {"code", "message", "request_id"}}` with a fixed, generic
message: 400 (unknown parameter), 401 (no valid session), 403 (CSRF), 404 (missing *or another
user's* resource: existence is never revealed), 409, 413, 415, 422 (validation: location and reason
only, the input is not echoed), 429, 500, 503 (database or storage unavailable). Stack traces,
SQL, paths and provider messages stay in the logs.

**Audit trail** (`audit_events`, written by `audit_event`, one row per event, in its own
transaction so denials are recorded even though the request fails): `session_created`,
`session_revoked`, `document_created`, `document_accessed` (download URL issued),
`document_deleted` (by the user or retention), `upload_completed`, `upload_rejected`,
`processing_started`, `processing_failed`, `processing_completed`, `export_created`,
`export_failed`, `authorization_denied`, `rate_limit_exceeded`, `quota_exceeded`,
`csrf_rejected`. Each row has the time, user, event, entity id and metadata (request id, session
id, result, reason, counts), never filenames or content. Only its own user can read it
(`GET /audit`); no endpoint updates or deletes it. Events without a known user (per-IP limits)
stay in the security log. If an audit row cannot be written, the request still succeeds and the
failure is logged at ERROR with the event.

## 12. Dependencies, CI and secrets

`.github/workflows/ci.yml`:

- `permissions: contents: read` for every job; no job uses repository secrets; checkouts do not
  persist credentials; third-party actions are pinned to full commit SHAs; no shell step
  interpolates `github.event.*` or branch names.
- **SAST:** Ruff with the flake8-bandit (`S`) rules on application code (each exception is a
  commented `noqa`).
- **Dependency policy:** Python runtime dependencies (`pip-audit` on the locked, non-dev export)
  fail the build on any known vulnerability (pip-audit reports no severity, so all count); npm
  production dependencies fail on high or critical (`npm audit --omit=dev --audit-level=high`).
  Development-only dependencies of both are audited and reported without failing the build,
  because they never run in production; treat a finding exploitable in CI as a failure by hand.
- **Secret scanning:** gitleaks over the full git history on every run.

Secrets live only in the hosting platforms' environment settings. `.env` files are git-ignored;
`.env.example` files hold placeholders. The web app has no `NEXT_PUBLIC_*` variables: its
`API_ORIGIN` and `STORAGE_ORIGIN` are server-side configuration and are not in the client bundle.

## 13. Development vs production

`ENVIRONMENT` is `development` (local), `test` (pytest and CI) or `production` (the default, so a
forgotten variable fails closed). Development and test behave the same and need no production
infrastructure (no clamd, no proxy secret, moto or a dev bucket).

| | Development / test (set explicitly) | Production (`ENVIRONMENT=production`, the default) |
|---|---|---|
| `APP_SECRET` (API only) | placeholders allowed | required; ≥ 32 bytes, not a known placeholder, varied |
| `TRUSTED_PROXY_SECRET` (API and web) | optional | required by the API; as strong as `APP_SECRET` |
| `OBJECT_STORAGE_ENDPOINT` | any | https |
| `DOCUMENT_RETENTION_DAYS` | 30 unless set | must be set |
| `ALLOWED_ORIGINS` | exact origins, no `*` | exact **https** origins, no `*` |
| Session cookie | `Secure` by default (Chrome/Firefox accept it on http://localhost) | `SESSION_COOKIE_SECURE` must be true |
| `DOCUMENT_SCANNER` | optional (unset = not scanned) | must be set (`clamav`, or `none` explicitly) |
| API docs | `/docs`, `/redoc`, `/openapi.json` | disabled (attack-surface reduction only) |
| HSTS | off | on (API and web) |
| Storage | moto or a dev bucket (moto enforces neither signed sizes nor checksums) | Cloudflare R2 / S3, private bucket |
| Memory cap | not applied on Windows | `RLIMIT_AS` on Linux |

Any production setting above that is missing or unsafe stops the API and worker at startup.

**Required in production.** API: `ENVIRONMENT=production`, `APP_SECRET` and `TRUSTED_PROXY_SECRET`
(generate each with `python -c "import secrets; print(secrets.token_urlsafe(48))"`),
`DATABASE_URL`, `OBJECT_STORAGE_*`, `ALLOWED_ORIGINS`, `DOCUMENT_SCANNER`,
`DOCUMENT_RETENTION_DAYS`. Worker: the same without `APP_SECRET` and `TRUSTED_PROXY_SECRET` (it
needs neither, and warns if it holds `APP_SECRET`), plus `CLAMAV_HOST`/`CLAMAV_PORT` when scanning.
Web: `API_ORIGIN`, `STORAGE_ORIGIN` and `TRUSTED_PROXY_SECRET` (the build fails on Vercel without
it). There is no `DEBUG` switch: FastAPI runs without debug, uvicorn without `--reload`, and the
API docs are off in production.

**Manual configuration** that code cannot do: HTTPS on every domain; bucket private, its CORS
allowing `PUT` with `Content-Type` and `x-amz-checksum-sha256` from the web origin only; lifecycle
rules applied once; clamd deployed and updated; the worker's service memory limit and user
(§15); database backups (docs/DEPLOYMENT.md §8).

## 14. Production architecture

```text
Browser ──HTTPS──▶ Vercel: Next.js pages + /api/v1 proxy (middleware.ts)
   │                    │  adds X-Prospect-Client-IP + TRUSTED_PROXY_SECRET, strips spoofs
   │                    ▼
   │               API: FastAPI on Railway/Render ──▶ PostgreSQL (managed)
   │                    │  POST /documents: row + signed PUT URL (uploads/<random>.pdf)
   │                    │  POST /documents/{id}/complete: verify, promote, enqueue job row
   │                    ▼
   └──signed PUT (the PDF itself)──▶ Private object storage (R2), lifecycle rules
                                          ▲
                        Worker (Railway/Render, polls processing_jobs)
                        verify → scan (clamd) → parse in a killable child → store
```

**Vercel audit.** On Vercel runs only the Next.js app: server-rendered pages and the middleware
proxy. It keeps no state: no filesystem writes, no in-memory sessions or queues (the browser
keeps its CSRF token in page memory only), no background work. PDFs never pass through Vercel:
the browser uploads them straight to storage with the signed URL, so function payload and time
limits do not apply to documents. The API and the worker are long-running services on
Railway/Render, not Vercel functions; their in-process state is limited to caches of settings and
the storage client. Rate-limit counters, quotas, sessions and the job queue live in PostgreSQL,
so any number of API instances agree. The worker's temporary files exist only for one attempt
(deleted in `finally`). There is no static-IP assumption anywhere.

## 15. Processing boundary and the worker security contract

**Boundary.** The API never parses a PDF. `POST /documents/{id}/complete` ends by inserting a
`processing_jobs` row (the request `process(document_id)`); the worker claims it with
`FOR UPDATE SKIP LOCKED`, and results go back only through the database. The HTTP request
lifecycle is independent of parsing time. Moving parsing to a separately isolated runtime means
replacing `run_isolated(analyze, …)` in `app/worker.py`; nothing in the API changes.

**Contract** the processing runtime must meet. Status today:

| Requirement | Status |
|---|---|
| Parse in a separate, killable process with a wall-clock timeout | **enforced** (`app/sandbox.py`) |
| Memory limit | **enforced** on Linux (`RLIMIT_AS`); also set the service memory limit |
| CPU limit | **enforced** on Linux (`RLIMIT_CPU` = timeout + 5 s) |
| No core dumps of document contents | **enforced** on Linux (`RLIMIT_CORE` = 0) |
| Temporary files removed after every attempt | **enforced** (per-attempt `TemporaryDirectory`) |
| No application master secret | **enforced by configuration**: the worker never reads `APP_SECRET` and logs a warning if it holds it; do not set it on the worker service |
| Non-root execution | **not enforced**: logged as a warning; configure the service user |
| Ephemeral, read-only application filesystem | **not enforced**: platform configuration |
| Minimal storage permission | **not enforced**: use a token limited to this bucket (read, write, delete; no bucket admin) |
| Minimal database permission | **not enforced**: the worker uses the API's database role; a restricted role is future work |
| No unnecessary network access | **not enforced**: the parser child could open connections; needs container egress rules |
| Process/PID limit | **not enforced** (`RLIMIT_NPROC` is per user, unsafe to set in-process) |
| Code-execution isolation | **not provided**: the child shares the worker's environment and credentials. A PyMuPDF exploit reaches them. This is P2 scope (a parse-only container with no secrets, gVisor/Firecracker) |

## 16. Authorization matrix (anonymous sessions)

Every resource belongs to one anonymous user; a session acts for exactly one user. Tested in
`tests/test_p15.py` (every id-taking endpoint, other session and no session) and
`tests/test_security.py`.

| Resource (id) | Same session | Different session | No session |
|---|---|---|---|
| Document metadata, pages, sections (`document_id`) | ALLOW | DENY (404) | DENY (401) |
| Original PDF (signed download URL) | ALLOW | DENY (404) | DENY (401) |
| Financial facts, calculations, financials (`document_id`, `fact_id`) | ALLOW | DENY (404) | DENY (401) |
| Evidence (`document_id` + `evidence_id`) | ALLOW | DENY (404) | DENY (401) |
| Export | ALLOW | DENY (404) | DENY (401) |
| Upload completion, delete, relabel | ALLOW | DENY (404) | DENY (401) |
| Fact review: accept/correct/reject/history (`fact_id`) | ALLOW | DENY (404) | DENY (401) |
| Diff (`document_id`, `other_id`) | ALLOW (both owned) | DENY (404) | DENY (401) |
| Company workspace (`company_id`) and its documents | ALLOW | DENY (404) | DENY (401) |
| Scenarios (`scenario_id`), data-quality issues (`issue_id`), watchlist | ALLOW | DENY (404) | DENY (401) |
| Processing job | not exposed; only its document's status | DENY | DENY |
| Audit events | READ own only, never modify | DENY (not listed) | DENY (401) |
| List endpoints (documents, companies, scenarios, review, quality, audit) | own rows | never another user's rows | DENY (401) |

`export_id`/`job_id`: exports are not stored and jobs have no endpoint, so no such id exists to
guess. A resource id alone never grants access: every query filters by the session's user
before anything else, and a foreign id is indistinguishable from a missing one (404).

## 17. Data classification

| Data | Class | Access | Logged? | Retention | Backup |
|---|---|---|---|---|---|
| Uploaded PDFs | HIGH | owner only, via short-lived signed URL | never content; id/size only | retention / workspace grace (§2) | not backed up (DEPLOYMENT §8) |
| Page text, evidence, financial facts, calculations | HIGH | owner only | never | with the document | database backups |
| Company workspaces, scenarios, reviews | HIGH | owner only | names never in audit metadata | with the user | database backups |
| Exports | HIGH | owner only, per request | counts/format only | never stored | — |
| Session token, CSRF token, cookies | HIGH (credential) | the browser only (HttpOnly) | never | session TTL; rows 7 days after expiry | database backups (session rows, never tokens) |
| `APP_SECRET`, `TRUSTED_PROXY_SECRET`, storage and DB credentials | HIGH (secret) | platform environment only | never | rotate on exposure | not in backups |
| Filenames, company labels | MEDIUM (user text) | owner only | never | with the document | database backups |
| Audit events | MEDIUM (ids, reasons) | owner read-only | yes (metadata) | with the workspace | database backups |
| Session/user/document ids | MEDIUM | server side | yes | with their records | database backups |
| Client IP addresses | MEDIUM (personal data) | server side | not logged; appear raw in rate-limit counter keys | counter rows deleted when their window ends (sweep) | database backups |
| Request ids, timings, status codes | LOW | server side | yes | log retention | — |

## 18. Consistency between storage and the database

Document states: `UPLOADING` (intent issued) → `UPLOADED` (verified, job queued) → `QUEUED` /
`PROCESSING` → `READY` or `FAILED`, plus `object_deleted_at` once a failed or abandoned file is
gone. No extra states were needed: every failure below resolves to one of these.

| Failure | What happens |
|---|---|
| Intent created, file never uploaded | `/complete` answers 409; after the URL expires the sweep marks it FAILED; storage lifecycle expires `uploads/` |
| File uploaded, database write in `/complete` fails | transaction rolls back (still `UPLOADING`, file still under `uploads/`); retrying `/complete` succeeds because the promoted key is derived from the upload key; a never-retried copy is an orphan that reconciliation removes |
| Database says stored, object missing | worker fails the document permanently ("file is missing"); reconciliation reports it |
| Object exists, no database row | reconciliation deletes it after the grace period (§9) |
| Processing succeeds, storing results fails | one transaction: nothing partial is kept; retried with backoff, then FAILED |
| Worker dies mid-job | lease expires, job reclaimed (bounded by `PROCESSING_MAX_ATTEMPTS`) |
| Delete: storage fails | nothing changes, 503, retry |
| Delete: database fails after storage | row remains, retry completes |
| Document deleted | all derived rows cascade; exports are never stored |
