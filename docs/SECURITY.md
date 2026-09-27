# Prospect Security Model

Prospect handles untrusted input: uploaded PDFs, filenames, request parameters, headers and
anything the browser sends. Every control below is enforced by the API or the worker; the web
client only mirrors some of them for a better message.

## 1. Threats covered (P0)

| Area | Control | Where |
|---|---|---|
| API abuse | Server-side rate limits, 429 + `Retry-After` | `app/ratelimit.py`, `app/auth.py` |
| Oversized uploads | Size signed into the storage URL; re-checked on completion | `app/storage.py`, `app/documents.py` |
| Token theft/replay | Signed, expiring, revocable session tokens | `app/auth.py` |
| Malicious PDFs | Parsing in a killable child process with timeout and limits | `app/sandbox.py`, `app/pipeline.py` |
| Retry amplification | Document failures never retried; infra retries bounded, backoff + jitter | `app/worker.py` |
| Unbounded reads | Paging, SQL-side counts before loading, company-scope cap | `app/documents.py`, `app/financials.py` |
| Export abuse | Rate limit, record and byte caps, no truncation | `app/financials.py` |
| Resource exhaustion | Per-user document, storage and processing quotas (race-safe) | `app/quotas.py` |
| Orphaned resources | Worker sweep: abandoned uploads, failed objects, stale counters | `app/worker.py` `sweep` |

**Limit of the parser sandbox.** The child process is a resource boundary (time, memory), not a
code-execution boundary: it inherits the worker's environment variables and returns its result
by pickle over a pipe. A PyMuPDF memory-corruption exploit in the child would reach the worker's
credentials. Stronger isolation needs a separate container without database or storage secrets
(e.g. a parse-only service, gVisor/Firecracker), which is outside P0.

Unchanged protections: every document query is scoped by `document.user_id == <session user>`
(`_owned_document`); SQL is built with SQLAlchemy (parameterized); storage keys are random, never
derived from filenames; extracted PDF text is rendered as escaped text (no `dangerouslySetInnerHTML`,
`eval` or `new Function` in the web app); CSV exports escape spreadsheet formulas.

## 2. Anonymous sessions and token lifecycle

There are no accounts yet. `POST /api/v1/sessions` creates an anonymous user and a session and
returns a token:

```text
v1.<session_id>.<issued_at>.<expires_at>.<HMAC-SHA256(APP_SECRET, first four fields)>
```

A request is authenticated only if the token is well formed, the signature matches, `expires_at`
is in the future, and the `sessions` row exists, is not revoked and is not expired. Anything else
is `401`. The session's user id scopes every query; the client never names an owner.

| Endpoint | Purpose |
|---|---|
| `POST /sessions` | new anonymous user + token (rate limited per client IP) |
| `POST /sessions/refresh` | new token for the same user; the old session is revoked |
| `DELETE /sessions/current` | revoke this token now (sign out) |

Tokens live `SESSION_TTL_SECONDS` (default 24 h). The web client refreshes once a token is past
half its lifetime, so an active browser keeps its documents; a token that expires unused cannot be
recovered (anonymous data is tied to it). Revoking one session does not require rotating
`APP_SECRET`; rotating `APP_SECRET` invalidates every token at once.

## 3. Uploads

1. `POST /documents` validates the declared type and size (`MAX_UPLOAD_BYTES`, default 50 MiB),
   checks quotas, and returns a presigned PUT URL whose signature covers `Content-Length` (the
   declared size) and `Content-Type: application/pdf`. S3/R2 recompute the signature from the
   actual request, so a body of any other length is refused by storage before the API sees it.
   (R2 does not support presigned POST policies, so `content-length-range` is not available.)
2. The browser also sends the file's SHA-256.
3. `POST /documents/{id}/complete` re-reads the stored object: size must equal the declared size
   (and be within the limit), stored content type must be `application/pdf`, and the first KiB
   must contain `%PDF-`. Otherwise the object is deleted and the document is `FAILED`.
4. The worker hashes the downloaded file and refuses to parse it if it differs from the SHA-256.

Filenames are display text only. Uploads never completed are cleaned up after the URL expires.

## 4. Processing limits

The worker downloads the PDF to a temporary directory (always deleted), then runs
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

Failure messages shown to users are fixed strings ("Document processing failed.", "Document
processing took too long and was stopped."); exception details stay in the logs.

**Retries.** Failures caused by the document (unreadable, over a limit, timeout, crash, checksum)
are permanent: retrying would only repeat the work. Infrastructure errors (storage, database) are
retried up to `PROCESSING_MAX_ATTEMPTS` (3) after `PROCESSING_RETRY_BASE_SECONDS × 2^(n−1)` plus up
to 50% jitter. A job whose worker died is reclaimed after `PROCESSING_LEASE_SECONDS` (must exceed
the timeout) and counts as an attempt.

## 5. Quotas (per user)

| Setting | Default | Counted |
|---|---|---|
| `QUOTA_MAX_DOCUMENTS` | 100 | documents not FAILED |
| `QUOTA_MAX_STORAGE_BYTES` | 2 GiB | bytes stored or reserved by in-progress uploads |
| `QUOTA_MAX_ACTIVE_JOBS` | 3 | queued + running jobs |
| `QUOTA_MAX_DAILY_JOBS` | 50 | jobs created in the last 24 h |

Checks lock the user's row (`SELECT … FOR UPDATE`) in the same transaction as the insert, so
parallel requests cannot both pass on the last slot. Document/storage quota → `409 quota_exceeded`;
processing quota → `429 quota_exceeded` (the upload stays pending and can be completed later).

## 6. Rate limits

Fixed windows counted in PostgreSQL (shared by all API instances; one atomic upsert per request).
Format `<requests>/<window seconds>`. Anonymous endpoints count per client IP; authenticated ones
per user (so refreshing a token does not reset them).

| Setting | Default | Endpoints |
|---|---|---|
| `RATE_LIMIT_SESSIONS` | 5/60 per IP | `POST /sessions` |
| `RATE_LIMIT_SESSION_REFRESH` | 10/3600 | `POST /sessions/refresh` |
| `RATE_LIMIT_UPLOADS` | 20/3600 | `POST /documents` |
| `RATE_LIMIT_COMPLETE` | 30/3600 | `POST /documents/{id}/complete` |
| `RATE_LIMIT_FINANCIALS` | 60/60 | `GET /documents/{id}/financials` |
| `RATE_LIMIT_COMPUTE` | 30/60 | diff, scenario preview, data quality |
| `RATE_LIMIT_EXPORT` | 10/60 | `GET /documents/{id}/export` |

Over the limit: `429 rate_limited` with `Retry-After` (seconds until the window resets).

**Client IP behind a proxy.** The IP is `request.client`, which uvicorn takes from
`X-Forwarded-For` only for proxies in `FORWARDED_ALLOW_IPS` (default `127.0.0.1`). On Railway/Render
set `FORWARDED_ALLOW_IPS="*"` only if the API is reachable exclusively through the platform proxy;
otherwise a client could spoof the header. Without it, all users share the proxy's IP bucket.

## 7. Financial data and exports

- `GET /documents/{id}/metrics` is paged in SQL: `limit` (default `PAGE_DEFAULT_LIMIT` 100, at most
  `PAGE_MAX_LIMIT` 500, larger is `422`) and `offset`; the response has `next_offset`.
- Any unpaged load of facts (financials, exports, diff, quality, watchlist) counts rows in SQL first
  and refuses more than `FINANCIALS_MAX_FACTS` (10,000) with `413 financial_data_too_large`.
- Company scope is capped at `FINANCIALS_MAX_DOCUMENTS` (20) reports.
- Page text is never loaded to build fact lists (only the page label).
- Exports: rate limited; more than `EXPORT_MAX_RECORDS` (20,000) rows or `EXPORT_MAX_BYTES`
  (20 MiB) → `413 export_too_large`, never a silently shortened file. Exports are built in memory
  within those caps (no temporary files); larger exports would need a background job, which does not
  exist yet.

## 8. Cleanup

The worker runs `sweep` every 5 minutes: uploads still `UPLOADING` after the signed URL expired
(plus 60 s) are marked FAILED and their object deleted; objects of FAILED documents are deleted
(`object_deleted_at` records it, and a failed delete is retried next time); expired rate-limit
counters and sessions expired for over 7 days are removed. An object is only deleted once nothing
can still write or read it.

## 9. Logging and errors

Clients get a generic message and a request id; stack traces and internal errors stay in logs.
Security events are structured JSON on the `prospect.security` logger with `event`, `request_id`,
`user_id`, `session_id` where known: `session_invalid`, `session_expired`, `session_revoked`,
`rate_limit_exceeded`, `upload_rejected_size`, `upload_rejected_type`, `upload_checksum_mismatch`,
`quota_exceeded`, `authorization_denied`, `processing_timeout`, `processing_resource_limit`,
`financial_data_limit_exceeded`, `export_limit_exceeded`. Tokens, signed URLs, secrets, document
text and evidence content are never logged.

## 10. Development vs production

| | Development (`ENVIRONMENT=development`, set explicitly) | Production (`ENVIRONMENT=production`, the default) |
|---|---|---|
| `APP_SECRET` | placeholders allowed | ≥ 32 bytes, not a known placeholder, varied; else the API and worker refuse to start |
| Storage | moto or a dev bucket (moto does not enforce signed sizes) | Cloudflare R2 / S3, private bucket |
| Memory cap | not applied on Windows | `RLIMIT_AS` on Linux |
| Proxy IPs | direct | set `FORWARDED_ALLOW_IPS` for the platform proxy |

`ENVIRONMENT` defaults to `production` (fail closed): local development, CI and tests set
`ENVIRONMENT=development` explicitly (see `apps/api/.env.example`).

**Required in production:** `APP_SECRET` (generate with
`python -c "import secrets; print(secrets.token_urlsafe(48))"`), `DATABASE_URL`,
`OBJECT_STORAGE_ENDPOINT`, `OBJECT_STORAGE_BUCKET`, `OBJECT_STORAGE_ACCESS_KEY`,
`OBJECT_STORAGE_SECRET_KEY`, `CORS_ORIGINS` (the deployed frontend only). Everything else has a
safe default and may be tuned.

**Recommended infrastructure:** managed PostgreSQL (also holds rate-limit counters); private object
storage (R2) with CORS limited to the frontend origin; the worker as its own service (it spawns the
parser processes) with a memory limit set on the service itself as a second boundary. Redis is not
required; move the rate-limit counters there if their write load ever matters.
