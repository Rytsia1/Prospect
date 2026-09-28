# P2 Adversarial Security Audit

This audit covers commit `6b54f4f` (after P0, P1 and P1.5) and was carried out on 2026-09-28. It is an audit only: no application code was changed.

Every finding has a reproduction in [`apps/api/tests/test_p2_adversarial.py`](../apps/api/tests/test_p2_adversarial.py), written as an `xfail(strict=True)` test that asserts the secure behaviour. The test fails today. The day the fix lands it XPASSes, which fails the run until its marker is removed. The remediation phase works from this list.

**Scope:**
- the API (`apps/api`);
- the web app and its proxy (`apps/web`);
- the worker and the parser sandbox;
- configuration;
- CI.

The testing was local only: PostgreSQL, moto S3, and `next dev` against a request-logging stub. It never touched real R2, Vercel or any other external system.

> **Status after P2.5 (2026-09-28):** P2-F1…F7 are fixed. Their tests in
> `test_p2_adversarial.py` now pass as ordinary regression tests.
> - I1 (pickle channel) and I2 (mutable CI image tag) are fixed.
> - I5 is fixed: control characters are now refused in all free text.
> - I4 is reduced: reflected values are bounded to 40 characters.
> - I3, I6 and I7 are unchanged.
>
> See [SECURITY_P2_5.md](SECURITY_P2_5.md).

## 1. Summary

| | |
|---|---|
| Attack surfaces tested | 46 API operations + `/health`; the web proxy and middleware; worker, sandbox and parser; storage and signed URLs; CI and supply chain |
| Findings | 7: **P0 0 · P1 0 · P2 2 · P3 2 · P4 3**, plus 7 informational notes |

**The primary question** is whether one anonymous session can access, modify, delete, process or export another session's resources. No exploitable path was found within the tested scope.

- Every endpoint that takes an id was tested with another session's ids and with no session. The owner check held in every case.
- Combinations of ids from different owners were also tested. Only one endpoint accepts a foreign id: it stores another session's company id, without reading or changing that session's data (P2-F3).

**The two medium findings are about availability, not confidentiality:**
- the API reads unbounded request bodies before authenticating (P2-F1);
- one anonymous session can write unbounded data to PostgreSQL (P2-F2).

This audit does not show that Prospect is secure. It shows what the attacks listed here could and could not do.

## 2. Attack surface

**Auth column:**
- **S**: a session is required (cookie or Bearer);
- **CSRF**: an unsafe method sent with a cookie requires a trusted Origin/Referer and `X-CSRF-Token`; Bearer clients are exempt;
- **IP**: a per-IP limit applies.

**Owner:** ownership of every id in the path or body is checked against `session.user_id`, and any other owner gets a 404.

| Endpoint | Method | Auth | CSRF | Resource ids | Sensitive output | Mutates | File | Rate limit | Quota |
|---|---|---|---|---|---|---|---|---|---|
| `/sessions` | POST | none | Origin must be trusted if present | – | CSRF token, cookie | ✓ | | IP/min + IP/day | |
| `/sessions/current` | GET | S | | session | CSRF token | | | | |
| `/sessions/current` | DELETE | S | ✓ | session | | ✓ | | | |
| `/sessions/refresh` | POST | S | ✓ | session | new cookie | ✓ | | user | |
| `/documents` | POST | S | ✓ | – | signed PUT URL | ✓ | ✓ | user + IP | documents, bytes |
| `/documents` | GET | S | | – | metadata | | | | limit ≤ 100 |
| `/documents/{id}/complete` | POST | S | ✓ | document | | ✓ | ✓ | user + IP | jobs (user, global) |
| `/documents/{id}` | GET, PATCH, DELETE | S | ✓ (unsafe) | document | metadata | ✓ | ✓ (DELETE) | | |
| `/documents/{id}/download-url` | GET | S | | document | signed GET URL | | ✓ | | |
| `/documents/{id}/pages[/{n}]`, `/sections`, `/metrics`, `/calculations` | GET | S | | document | page text, facts, evidence | | | | paged/capped |
| `/documents/{id}/financials` | GET | S | | document (+ company scope) | facts, evidence | | | user | capped |
| `/documents/{id}/evidence/{eid}` | GET | S | | document + evidence (both checked) | evidence | | | | |
| `/documents/{id}/export` | GET | S | | document | all data, as a file | | ✓ | user + IP | records/bytes |
| `/documents/diff`, `/documents/{id}/diff` | POST, GET | S | ✓ (POST) | two documents (both checked) | facts, text | ✓ (writes a comparison) | | user | |
| `/financial-facts/review` | GET | S | | document filter | facts | | | | limit ≤ 200 |
| `/financial-facts/{id}/accept`, `/correct`, `/reject` | POST | S | ✓ | fact → document | fact | ✓ | | | |
| `/financial-facts/{id}/history` | GET | S | | fact → document | review history | | | | |
| `/data-quality` | GET | S | | document, company filters | issues | ✓ (**GET writes**) | | user | |
| `/data-quality/{id}` | PATCH | S | ✓ | issue | issue | ✓ | | | |
| `/scenarios/calculate` | POST | S | ✓ | document | facts | | | user | |
| `/scenarios` | POST, GET | S | ✓ (POST) | document, **company (unchecked, P2-F3)** | scenario | ✓ | | **none** | **none** |
| `/scenarios/{id}` | GET, PATCH, DELETE | S | ✓ (unsafe) | scenario | scenario | ✓ | | | |
| `/companies` | POST, GET | S | ✓ (POST) | – | companies | ✓ | | **none** | **none** |
| `/companies/{id}` | GET, PATCH, DELETE | S | ✓ (unsafe) | company | financials | ✓ | | | |
| `/companies/{id}/documents[/{doc}]` | POST, DELETE | S | ✓ | company + document (both checked) | metadata | ✓ | | | |
| `/watchlist`, `/watchlist/{company}` | GET, POST, DELETE | S | ✓ (unsafe) | company | facts | ✓ | | | |
| `/audit` | GET | S | | own rows only | own audit trail | | | | limit ≤ 200 |
| `/health` | GET | none | | – | `{"status":"ok"}` | | | | |
| `/docs`, `/redoc`, `/openapi.json` | GET | none | | – | schema | | | | disabled in production |

**Surfaces that do not exist** (checked, not assumed):
- WebSocket or SSE endpoints;
- job endpoints: jobs are database rows that the worker polls;
- stored exports: each export is generated per request and never stored;
- admin, debug or internal routes;
- any server-side fetch of a URL.

**Signed URLs:**
- a PUT URL is issued by `POST /documents`;
- a GET URL is issued by `/download-url`;
- storage itself is reached only through these URLs.

**Worker:** its only network surface is `:PORT/health`.

## 3. Findings

### [P2] P2-F1: Request bodies are unbounded and parsed before authentication

**Affected:** every JSON endpoint (FastAPI, `app/main.py`). No middleware limits body size, and uvicorn has no default limit.

**Impact:** availability.
- An unauthenticated client can make the API read and JSON-decode an arbitrarily large body.
- Memory use grows with body size times concurrency, so a few parallel requests can exhaust the API process.
- The API origin is public: Vercel has to reach it, so anyone can.

**Preconditions:** none; no session is needed.

**Reproduction:**
- Send `POST /api/v1/companies` with `Content-Type: application/json` and a malformed 50 MiB body, with no cookie.
- It is answered **422 `json_invalid`**, not 401. The body was read and decoded in full before authentication.
- A well-formed 50 MiB body gets its 401 only after the same parse.

**Expected:** an oversized body is refused with 413 before it is read or JSON-parsed, and certainly before any work is done for an unauthenticated client.

**Actual:** 422 after a full read and decode.

**Root cause:** FastAPI parses the request body before it resolves the route's dependencies (including `current_auth`). No layer caps `Content-Length` or counts streamed bytes.

**Recommended fix:**
- Add a small ASGI middleware that rejects a `Content-Length` over a limit and counts streamed bytes for chunked requests.
- 1 MiB is a reasonable limit: the largest real JSON body is a few KB, and PDFs never pass through the API.
- Also set a proxy-level limit where the platform allows one.

**Regression test:** `test_oversized_request_bodies_are_refused_before_they_are_parsed`

### [P2] P2-F2: One anonymous session can write unbounded data to the database

**Affected:**

| Endpoint | Unbounded input |
|---|---|
| `POST /companies`, `PATCH /companies/{id}` | `description` (no maximum length) |
| `POST /scenarios`, `PATCH /scenarios/{id}` | `assumptions` (any JSON), `base_period` (no maximum length) |
| accept / correct / reject a fact | `reason` |
| `PATCH /data-quality/{id}` | `reason` |

None of these create endpoints has a rate limit or a count quota. `GET /data-quality` and the diff endpoints also write a row on every call. They have a per-user rate limit, but a new session starts with a fresh one.

**Impact:** availability of the whole service.
- The managed PostgreSQL disk fills up, which affects every user.
- The data stays for as long as the attacker keeps the session alive. Workspace expiry only removes it 24 h after the session stops being usable.

**Preconditions:** one anonymous session (`POST /sessions` allows 50 per IP per day).

**Reproduction:**
- A 20 MiB `description` → **201**. It is stored, and echoed back in a 20 MiB response.
- A 5 MB `assumptions` object → **201**.
- 200 `POST /companies` requests in 2.8 s → all **201**.

**Expected:** field lengths are bounded (422), and creating these objects is limited per user and per IP.

**Actual:** neither is bounded.

**Root cause:** the P0/P1 quotas cover only documents and processing. The Phase 6 endpoints were added without `max_length`, rate limits or count quotas.

**Recommended fix:**
- `max_length` on every free-text field, for example:
  - `description` 2,000;
  - `reason` 1,000;
  - `base_period` 40, the same as `period_label`.
- Bound `assumptions`, by serialized size or with a typed schema.
- `limit_user(<bucket>, <ip bucket>)` on company and scenario creation.
- A per-user cap on the number of companies and scenarios.

**Regression tests:**
- `test_free_text_fields_are_bounded`
- `test_company_creation_is_rate_limited`

### [P3] P2-F3: A scenario accepts another session's `company_id`, which gives an existence oracle

**Affected:** `POST /scenarios` (`app/scenarios.py:create_scenario`).

**Impact:**
- **Tenant integrity:** the attacker's own scenario row stores another session's `company_id`.
- **Existence oracle:** the response is 201 when the company exists and 500 (foreign-key violation) when it does not.
- **No victim data is read or changed:**
  - the victim's scenario count filters by user;
  - deleting the victim's company cascades the attacker's row away.
- **Hard to exploit:** company ids are random UUIDv4, so the oracle needs an id that has already leaked.

**Preconditions:** a session with its own READY document, and a candidate company id.

**Reproduction:**
- `POST /scenarios {"document_id": <own>, "company_id": <victim's>, …}` → **201**, with the `company_id` echoed back.
- The same request with a random UUID → **500**.

**Expected:** 404 in both cases, so the two are indistinguishable.

**Actual:** 201 and 500.

**Root cause:** only `document_id` is checked for ownership. Whenever `document_id` is present, `company_id` is used unchecked: the classic bug of authorizing one of two ids.

**Recommended fix:** when `company_id` is given, load it through `_owned_company` before using it, as `companies.py` already does.

**Regression test:** `test_scenario_cannot_reference_another_sessions_company`

### [P3] P2-F4: Export fails with 500 for any non-Latin-1 filename or company name

**Affected:** `GET /documents/{id}/export` (`app/financials.py`).

**Impact:** availability of a user's own exports.
- A document named, for example, `年度报告 2025.pdf` can never be exported in any format.
- No data leaks, and the error body is generic.

**Preconditions:** a filename or company name containing characters outside Latin-1.

**Reproduction:** `GET …/export?format=csv`, `json` or `xlsx` → **500** for all three.

**Expected:** 200 with an ASCII `filename=`, plus an RFC 6266 `filename*=UTF-8''…` if a non-ASCII name is wanted.

**Actual:** 500.

**Root cause:** the `Content-Disposition` sanitizer keeps every character for which `str.isalnum()` is true, and that includes all Unicode letters. HTTP header values must be Latin-1, so encoding the response header raises an error.

**Recommended fix:** keep only ASCII alphanumerics (`c.isascii() and c.isalnum()`), and optionally add `filename*`.

**Regression test:** `test_export_of_a_non_latin_filename_succeeds`

### [P4] P2-F5: Hostile values and uniqueness conflicts return 500 instead of 4xx

**Affected:**

| Endpoint | Input | Why it fails |
|---|---|---|
| `POST /financial-facts/{id}/correct` | `value` of `1e200000` or `1e-200000` | overflows PostgreSQL `numeric` |
| `POST /scenarios` | `target_margin` of `1e999999` | the field has no bounds |
| `PATCH /documents/{id}` and every free-text `reason` | a NUL byte (`\x00`) in `company_name` or `reason` | PostgreSQL text cannot contain NUL |
| concurrent `POST /companies` with the same name | – | `IntegrityError` |
| concurrent `POST /watchlist` | – | `IntegrityError` |
| `PATCH /companies/{id}` renamed onto an existing name | – | `IntegrityError` |

**Impact:** error-path robustness only.
- **What is returned:** every response is the generic `internal_error` body with a request id. No response contained a stack trace, SQL or a path; every case was checked. The failures do add noise to logs and alerting.
- **Duplicate companies:** case variants such as `Acme` and `acme` can race past the case-insensitive pre-check and create duplicates, because the database constraint is case-sensitive.

**Preconditions:** a session.

**Reproduction:** see the parametrized test.

**Expected:** 422 for invalid values, 409 for conflicts.

**Actual:** 500.

**Root cause:**
- the `Decimal` fields have no magnitude bounds;
- free text has no NUL or control-character filter (filenames already have one);
- conflicts are handled by check-then-insert, instead of relying on the unique constraints and handling `IntegrityError`;
- the case-insensitive check has no matching `lower(name)` unique index.

**Recommended fix:**
- bound the `Decimal` fields (`max_digits`, `ge`, `le`);
- reject control characters in free text by reusing the `_display_filename` rule;
- turn `IntegrityError` on the known constraints into 409;
- add a unique index on `(user_id, lower(name))` in a migration.

**Regression tests:**
- `test_hostile_values_are_rejected_not_a_server_error`
- `test_uniqueness_races_and_conflicts_are_409_not_500`

### [P4] P2-F6: `GET /data-quality` writes, and concurrent reads duplicate issues

**Affected:** `app/quality.py:get_data_quality`.

**Impact:** duplicate issue rows, which inflate the counts shown to the user, and database writes on a method that should be safe. The effect stays inside the user's own workspace.

**Reproduction:** two concurrent GETs for a fresh document store every issue twice. The test forces this interleaving with a barrier, so it is deterministic.

**Root cause:** check-then-insert, with no lock and no unique key on (document, rule, metric, period).

**Recommended fix:** either a unique constraint on the issue key with `ON CONFLICT DO NOTHING`, or the user-row lock that `quotas._lock_user` already uses.

**Regression test:** `test_concurrent_data_quality_reads_do_not_duplicate_issues`

### [P4] P2-F7: Deleting a document while it is processing raises an exception in the worker

**Affected:** `app/worker.py:process_next`.

**Impact:**
- **Resisted:** the document is not resurrected and no rows are orphaned, because foreign keys cascade. The worker's main loop catches the exception and keeps running.
- **The problem:**
  - `_store` fails because the document is gone;
  - `_requeue` then calls `get_one` on the job, which was deleted along with the document;
  - `NoResultFound` escapes `process_next` and is logged as a crash;
  - no `processing_failed` audit entry is written.

**Reproduction:** delete the document between parsing and storing. The test does this by patching `run_isolated`.

**Recommended fix:** in `_store`, `_fail` and `_requeue`, treat a job or document that has vanished as "deleted by its owner": log it and return.

**Regression tests:**
- `test_worker_handles_a_document_deleted_mid_processing` (xfail)
- `test_deleting_during_processing_never_resurrects_the_document` (passes)

### Informational notes (P4, no test)

| # | Note |
|---|---|
| I1 | The parser child sends its result to the worker with **pickle** over the pipe. Today this crosses no boundary: the child runs as the same user, with the same environment and credentials. Once the child is less privileged than the parent, a compromised child could escalate through unpickling. When parser isolation is built, replace pickle with a plain data format such as JSON. |
| I2 | CI uses the mutable image tag `pgvector/pgvector:pg16`; pin it by digest, as the actions already are. The actions are pinned to commit SHAs, `permissions` is `contents: read`, and no secrets are used. |
| I3 | Two filter checks are incomplete, affecting the same user only: `/data-quality?company_id=` filters the documents but not the issues it returns (all of the user's issues come back), and `DELETE /companies/{c}/documents/{d}` does not check that `d` belongs to `c`. |
| I4 | Some error messages reflect user input: `base_period` in `missing_base_fact`, and `metric_key` or `scale` in review errors. This is not XSS: the responses are JSON only, the API sends `CSP default-src 'none'` and `nosniff`, and React renders the message as text. It does make responses large; a 100 KB period is echoed back in full. |
| I5 | Company names, descriptions and reasons keep control characters such as ESC and bidi overrides, whereas filenames have them stripped. There is no injection, because React renders them as text and logs JSON-escape them; removing them is good hygiene (see P2-F5). |
| I6 | The `Bearer` scheme is matched case-sensitively: `bearer x` gets a 401, which is safe. `GET /documents/` answers with a 307 redirect to `/documents`. |
| I7 | The web middleware skips requests that carry `Purpose: prefetch` or `Next-Router-Prefetch`. Because there is no fallback rewrite, such `/api/v1` requests get a Next 404, so the header stripping is never bypassed. Keep it that way: never re-add a static `/api/v1` rewrite to `next.config.ts`. |

## 4. Attacks that were resisted

Each has a test, either in `test_p2_adversarial.py` or in the earlier suites (`test_security*.py`, `test_p15.py`).

**Cross-session access (IDOR/BOLA):**
- All 32 id-taking operations were called with another session's ids (403/404) and with no session (401). The owner's data stayed unchanged.
- The list and search endpoints never return another session's rows, even when filtered by that session's ids:
  - `/documents`
  - `/companies`
  - `/scenarios`
  - `/financial-facts/review`
  - `/data-quality`
  - `/watchlist`
  - `/audit`
- Nested ids are checked on both sides:
  - evidence ↔ document;
  - the company ↔ document association;
  - both documents of a diff;
  - fact → document;
  - company scope.
- An unguessable UUID on its own never grants access.

**Sessions:**
- These tampered tokens are rejected:
  - a signature moved onto another session id;
  - an extended expiry;
  - a changed version;
  - a re-cased signature.
- Empty, garbage, 8 KB and 60 KB tokens get a 401, not an error.
- Revoked and expired sessions get a 401, and a refresh revokes the old token.
- Session fixation is not possible: the cookie is `__Host-`, HttpOnly and SameSite=Strict, and the server only ever issues fresh ids.
- A new session is an empty workspace. The per-IP limits (uploads, completion, export, sessions per day) do not reset with it.

**CSRF:** each of these is refused:
- a missing, empty, wrong, duplicated (`a, a`), re-cased, pre-refresh or other-session token;
- `Origin: null`, `Origin: file://`, or a foreign Origin;
- the Referer tricks `trusted.evil.example` and `evil@trusted`;
- a `text/plain` simple request.

Every unsafe method sent with a cookie goes through this same check, including complete, delete, refresh and sign-out.

**CORS:** foreign, `null`, `file://` and look-alike origins never get an `Access-Control-Allow-Origin` header, on either the preflight or the response. `Allow-Credentials` is never sent.

**Methods and paths:**
- PUT, OPTIONS, HEAD and TRACE on resources → 405.
- A double slash, a case variant or an encoded `%2F` → 404.

**Client-side path traversal:** a web route id of `..%2F..%2Fsessions%2Fcurrent` stays percent-encoded all the way to the API, where it matches no route. This was verified live with `next dev` and a logging stub.

**XSS:**
- No `dangerouslySetInnerHTML`, `innerHTML`, `eval` or `new Function` anywhere.
- Every `href` is built from server UUIDs or integers.
- The only `window.open` target is the signed URL issued by the server.
- Filenames, company names, evidence and page text are all attacker-controlled through the PDF, and React renders them as text.
- Pages are served with a nonce-based CSP, and API responses with `default-src 'none'` and `nosniff`.
- The CSV export escapes formula prefixes. The XLSX export writes inline strings, which are never formulas.

**SSRF:** no API or worker code fetches a URL derived from user input. The only outbound connections go to the configured storage endpoint and clamd, and the proxy target (`API_ORIGIN`) is fixed configuration.

**Uploads and storage:**
- The storage key is random, chosen by the server under `uploads/`, and never derived from the filename.
- Extra body fields such as `storage_key` or `user_id` → 422.
- The PUT URL is signed for the method, key, length, content type and SHA-256.
- Completion re-checks the stored size, content type and magic bytes, and the worker re-hashes the file.
- A wrong MIME type, a polyglot file and an oversized declaration were all rejected.
- Completing another session's upload → 404.

**Races:**
- 8 concurrent completes → one job.
- 8 concurrent deletes → one 204 and seven 404s.
- Complete after delete → 404.
- Concurrent uploads cannot exceed the per-user or per-IP quota (P1/P1.5 tests).
- Concurrent refresh → one winner.

**Hostile PDFs:** each one ended as a safe rejection or a harmless parse inside the killable child, in under 5 s, and the worker process was unaffected. They were:
- a flate bomb: 50 MB, and 400 MB during exploration;
- array nesting 100k deep and dictionary nesting 30k deep;
- a page-tree cycle;
- a claimed page count of 999,999,999;
- JavaScript, Launch and URI actions, plus an embedded file;
- an external image reference;
- a corrupt xref and stream;
- 50k objects, and 300k during exploration.

**Information disclosure:** invalid UUIDs, invalid JSON, validation failures, a storage outage and every 500 found above all return the generic error body. None contains a stack trace, path, SQL, secret or another user's id, and the seeded fuzz checks this on every response.

**Audit and log integrity:**
- No endpoint writes, updates or deletes audit rows directly.
- The actor always comes from the session.
- Newlines, JSON delimiters and ANSI escapes in names, `Origin` and request ids stay inside JSON-escaped log fields, and unsafe request ids are replaced.

**Frontend trust boundary:** every security decision is made on the server:
- ownership;
- quotas and rate limits;
- CSRF;
- file validation;
- the storage key.

Ids generated by the frontend are never used. `localStorage` only held a legacy token, which is removed on the first page load.

**Bounded fuzzing:** 420 seeded requests across the 13 endpoints that take a body. The values covered XSS, spreadsheet formulas, paths, Unicode, numeric extremes, type confusion and ids of other resources. There were no 500s and no leaks, apart from the P2-F5 classes, which were excluded from the fuzz and are recorded above.

## 5. Remaining risks (architectural, not fixed in P2)

| Risk | Status |
|---|---|
| **PDF parser isolation** | **Not a security boundary.** The parser runs in a child process of the worker, with the worker's user, environment and credentials: database and storage keys, and no network restriction. On Linux the child has CPU, memory and core-dump limits; on Windows it only has the wall-clock kill. Because the parser runs in the worker and not the API, a parser crash cannot take down the API. Confidentiality is not separated. The pickle channel is note I1. |
| **Anonymous session model** | Every cross-session attack tested was resisted. By design there is no recovery: a lost cookie is a lost workspace. Sessions, uploads, completion and export are limited per IP. Companies, scenarios and free text are **not** (P2-F2), and users behind the same NAT or CGNAT share one IP's limits. |
| **Vercel proxy trust** | Implemented and tested against the Next runtime in P1.5, but not verified on real Vercel. It relies on Vercel overwriting `x-real-ip` / `x-forwarded-for`, and on `TRUSTED_PROXY_SECRET` staying secret. |
| **Object storage consistency** | Handled, with reconciliation (P1.5). The orphan sweep deletes only under known prefixes, only after 48 h, and only after re-checking the database. It has been tested against moto only. |
| **R2 checksum enforcement** | **Unverified.** The opt-in suite `tests/integration/test_r2.py` exists but has not been run against a real bucket. The control that is actually enforced is the worker's own re-hash. |
| **Resource exhaustion** | P2-F1 and P2-F2 are open. The parser is bounded by timeout, pages, text, cells and facts, and by memory on Linux only. The global queue cap is approximate. |
| **Backup/recovery** | Documented in DEPLOYMENT.md §8 but **not configured**: PITR is not enabled and no restore test has been done. |

## 6. P2 exit criteria

- [x] attack surface mapped (§2)
- [x] anonymous session attacks tested
- [x] IDOR/BOLA tested, including mixed and nested ids
- [x] authorization matrix tested
- [x] CSRF bypass attempts tested
- [x] CORS tested
- [x] XSS tested (source review of every sink, plus stored-payload fuzzing)
- [x] upload validation attacked
- [x] malicious PDF testing performed
- [x] SSRF surface audited (none found)
- [x] rate-limit bypass tested (spoofed IP headers, new sessions, concurrency)
- [x] race conditions tested
- [x] resource exhaustion tested (bounded)
- [x] database/query abuse tested (ORM only, no raw SQL built from user input, limits on list endpoints)
- [x] object storage tested
- [x] signed URLs tested (method, key and length binding in moto; enforcement by the provider is opt-in and was not run)
- [x] exports tested
- [x] information disclosure tested
- [x] business logic tested
- [x] audit log integrity tested
- [x] secrets and configuration reviewed (gitleaks found history and source clean; only `.env.example` placeholders and CI-only test credentials)
- [x] dependencies and supply chain reviewed (pip-audit and npm audit: 0 known vulnerabilities)
- [x] frontend trust boundary reviewed
- [x] bounded fuzzing performed
- [x] all findings documented
- [x] regression tests added for confirmed vulnerabilities (strict xfail)
- [x] existing test suite passes
