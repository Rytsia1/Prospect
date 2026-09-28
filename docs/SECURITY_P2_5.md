# P2.5 — PDF Processing and Data Security

Central assumption: **user input is hostile.** That covers:
- the PDF: bytes, metadata, text, structure;
- the filename;
- every id, header and query parameter;
- the frontend.

This document records what the code enforces, what is only *provided* (and must be applied at
deployment), and what remains open. It complements [SECURITY.md](SECURITY.md) and
[SECURITY_P2_AUDIT.md](SECURITY_P2_AUDIT.md). LLM/AI security is out of scope: Prospect has no LLM
pipeline.

## 1. Where things are

| Item | Location | Created by |
|---|---|---|
| Original PDF | Private bucket: `uploads/<random>.pdf` while unverified (1-day lifecycle), then `documents/<random>.pdf` | Browser (signed PUT); the API promotes it on `/complete` |
| Extracted text | `document_pages.text`, `document_chunks.content` | Worker, from the parser's result |
| Financial facts | `financial_facts`, `calculations`, `calculation_inputs` | Worker |
| Evidence | `evidence`: verbatim row, page, section, chunk, locator | Worker |
| Reviews, scenarios, quality issues | `extraction_reviews`, `scenarios`, `data_quality_issues` | API, on user action |
| Exports | Built in API memory per request, **never stored** | API |
| Temporary files | Worker: one `TemporaryDirectory` per attempt (the downloaded PDF). Parser: its own `TemporaryDirectory` (result file only) | Worker, sandbox |
| Database credentials | `DATABASE_URL`: API and worker, one role each (`deploy/db_roles.sql`) | Platform env |
| Storage credentials | `OBJECT_STORAGE_*`: API (sign, verify, delete) and worker (read, delete) | Platform env |
| `APP_SECRET` | API only (session and CSRF HMAC); the worker warns if it holds it | Platform env |
| `TRUSTED_PROXY_SECRET` | API and Vercel only | Platform env |
| Background processing | The worker polls `processing_jobs` (`FOR UPDATE SKIP LOCKED`), one job at a time per process; sweep hourly, reconciliation daily | Worker |

## 2. Trust boundaries

```text
 Browser (hostile)
   │ ①  HTTPS; cookie session + CSRF; JSON ≤ 1 MiB
   ▼
 Vercel (Next.js pages + /api/v1 proxy)        holds: TRUSTED_PROXY_SECRET
   │ ②  HTTPS; X-Prospect-Client-IP + proxy secret
   ▼
 API (FastAPI)                                 holds: APP_SECRET, proxy secret, DB role "api", storage token
   │ ③ rows          │ ④ signed URL → the browser PUTs the PDF straight to storage
   ▼                 ▼
 PostgreSQL        Private bucket (R2)
   ▲                 ▲
   │ ⑤ jobs, results │ ⑤ download
 Worker                                        holds: DB role "worker", storage token; NOT APP_SECRET
   │ ⑥ file path + limits (worker → child: trusted direction)
   ▼
 Parser child (treated as hostile once parsing starts)   holds: nothing; no network where namespaces exist
   │ ⑦ result file (size-capped) → allowlist unpickler → worker stores it for this job only
```

| # | Data crossing | Credentials crossing | Permissions on the far side | A compromised near side gains |
|---|---|---|---|---|
| ① | Requests, JSON, cookie | Session cookie (HttpOnly) | Only that session's workspace | Only its own workspace |
| ② | Proxied requests, client IP | Proxy secret | The API trusts the IP header only with the secret | Vercel compromise → spoofed IPs for rate limits; no data without sessions |
| ③ | Rows | API DB role (DML only, once `db_roles.sql` is applied) | All rows of all users | API compromise → **all users' data** (the API is the authorization point) |
| ④ | PDF bytes | Signed URL: one key, PUT, exact length, content type, SHA-256, 15 min | That object | Nothing beyond that object |
| ⑤ | Jobs, pages, facts, evidence; PDFs | Worker DB role, storage token | All rows, all objects | Worker compromise → **all users' data and files** |
| ⑥ | File path, limits | **None** (allowlisted environment) | – | – |
| ⑦ | Parse result | None | Stored for the job's own document | See §3 |

## 3. The central question: a compromised parser

What code execution in the PDF parser (a PyMuPDF/MuPDF memory-corruption exploit) reaches:

| Target | Reachable? | Why |
|---|---|---|
| `DATABASE_URL`, storage keys, `APP_SECRET` in the parser's environment | **No** | The child starts with `PATH`/`SYSTEMROOT`/locale only (tested for every secret) and, by construction, imports only the parser modules, never `app.config` |
| The worker's environment or memory (`/proc/<pid>/environ`, `/proc/<pid>/mem`, ptrace) | **No, on Linux** | The worker sets `PR_SET_DUMPABLE=0`, so its `/proc` entries become root-owned; Yama `ptrace_scope ≥ 1` (the Debian/Ubuntu default) also blocks tracing a non-descendant. Development on Windows has no equivalent |
| Code execution in the worker through its result | **No** | The result is a size-capped file, unpickled with an allowlist (result dataclasses, `Decimal`, `date`). Tested with a hostile payload and with a disallowed type |
| Network: database host, metadata endpoint, internal services | **No, where unprivileged user namespaces are allowed** (empty network namespace). **Yes otherwise**, though it holds no credentials to use. `PROCESSING_NETWORK_ISOLATION=required` refuses to parse without isolation |
| Other users' documents | **Not through the app**: only this job's PDF is on disk, in a per-attempt directory deleted afterwards. **But** the child runs as the worker's OS user and can read whatever that user can read |
| Forging results for its own document | **Yes, inherently**: the parser decides what the PDF says. Results are bounded and stored only for the job's own document, which the attacker uploaded |
| Persistence | **Limited**: `RLIMIT_FSIZE` bounds what it writes, and its directory is deleted. It could still write elsewhere the OS user may, create many files (the count is not limited), or fork a process that escapes the process-group kill with `setsid`. The worker reads its result only as a regular file (no symlink or FIFO), capped in size |

**Verdict:**
- A parser compromise no longer yields credentials or the worker process.
- It is **still not a sandbox**: the parser shares the OS user, kernel and filesystem view with
  the worker, and network isolation depends on the host.
- This is reported as an architectural risk in §20.

## 4. Worker and parser isolation

| Control | Status |
|---|---|
| The API never parses PDFs; processing goes through `processing_jobs` | enforced |
| Parser in a separate process with a hard wall-clock timeout; killed and FAILED, never stuck in `processing` (lease reclaim as backstop) | enforced, tested |
| Parser has an allowlisted environment, never loads settings, has stdout/stderr discarded and its own temporary directory | **enforced (P2.5)**, tested |
| Parser has `RLIMIT_CORE=0`, `RLIMIT_CPU`, `RLIMIT_AS`, `RLIMIT_FSIZE` | enforced on Linux |
| Parser runs in an empty network namespace | enforced where the host allows it; `required` makes it mandatory; `off` is refused in production |
| Result channel: size cap + allowlist unpickler | **enforced (P2.5)**, tested |
| Worker not dumpable | **enforced on Linux (P2.5)** |
| Worker holds no `APP_SECRET` or proxy secret | configuration (a warning if present) |
| Non-root user, read-only root filesystem, dropped capabilities, seccomp, PID limit, separate kernel | platform configuration, or **not provided** |

**Target architecture:** the parser runs in its own runtime (gVisor, Firecracker, or a container
with no credentials, no egress and a read-only root). Getting there needs **no application
change**: replace the `subprocess` launch in `app/sandbox.run_isolated`. The input (path and
limits) and output (bounded, allowlisted result) stay as they are.

## 5. Least privilege and secrets

**Database.** `apps/api/deploy/db_roles.sql` creates the `prospect_app` group:
- it allows DML on the application tables;
- it forbids DDL, `TRUNCATE`, role management and `alembic_version` writes.

The API and the worker each get their own login in that group. Migrations use the owner, from the
deploy step only.

A test applies the script and proves that a service login:
- can read rows;
- **cannot** create, alter, drop or truncate tables, change the schema version, or create roles.

The worker cannot have a narrower role, because its sweep deletes whole expired workspaces.

**Storage.** Use one token per service, scoped to this bucket (object read, write and delete; no
bucket administration). R2 tokens cannot separate users by prefix, so object authorization is
always the API's ownership check (§13).

| Secret | Needed by | Grants | Never given to |
|---|---|---|---|
| `DATABASE_URL` (api role) | API | DML on all rows | worker, Vercel, parser, CI |
| `DATABASE_URL` (worker role) | Worker | DML on all rows | API, Vercel, parser, CI |
| Owner credential | Deploy/migration step | DDL | every running service |
| Storage token(s) | API, worker | objects in the one bucket | Vercel, parser, CI |
| `APP_SECRET` | API | forging any session or CSRF token | worker, Vercel, parser |
| `TRUSTED_PROXY_SECRET` | API, Vercel | naming the client IP | worker, parser |
| Deploy tokens (Vercel, Railway, Cloudflare) | people, via the platforms' Git integration | deploys, reading env vars | CI jobs for pull requests |
| CI | none: no job uses a repository secret | – | – |

## 6. Network

| Component | Needs | Status |
|---|---|---|
| Parser | Nothing | Denied where namespaces allow (§4) |
| Worker | Database, storage, clamd | Restrict egress to these at the platform, where it can |
| API | Database, storage | – |
| Web proxy | The API origin | – |

**SSRF.** No component fetches a URL derived from user input. The PDF library never resolves
links, remote images, embedded files or JavaScript. Hostile fixtures pointing at `127.0.0.1` and
`169.254.169.254` were parsed without any connection attempt.

## 7. Resource limits

| Limit | Setting (default) | Enforced by |
|---|---|---|
| PDF size | `MAX_UPLOAD_BYTES` (50 MiB) | Storage signature (exact length) + `/complete` + worker re-check |
| Pages | `PROCESSING_MAX_PAGES` (2000) | Parser, before any page loads |
| Objects | `PROCESSING_MAX_OBJECTS` (500,000) | Parser, before any page loads (**P2.5**) |
| Processing time | `PROCESSING_TIMEOUT_SECONDS` (120) | The worker kills the child |
| CPU | `RLIMIT_CPU` = timeout + 5 s | Kernel (Linux) |
| Memory | `PROCESSING_MAX_MEMORY_BYTES` (2 GiB) | `RLIMIT_AS` (Linux) + service memory limit |
| Extracted text | `PROCESSING_MAX_TEXT_BYTES` (50 MB) | Parser, page by page |
| Table cells | `PROCESSING_MAX_TABLE_CELLS` (500,000) | Parser, before cells are read |
| Facts / evidence | `PROCESSING_MAX_FACTS` / `_EVIDENCE` (5000) | Pipeline; never a truncated subset |
| Parse result and parser disk writes | `PROCESSING_MAX_RESULT_BYTES` (256 MiB) | Parent size check + `RLIMIT_FSIZE` (**P2.5**) |
| Worker temporary storage | One PDF per attempt, deleted after | Worker design |
| Concurrent jobs | 1 per worker process × instances; `QUOTA_MAX_ACTIVE_JOBS` (3/user); `QUOTA_MAX_QUEUED_JOBS` (500 global) | Worker loop, quotas |
| Request body | `MAX_REQUEST_BODY_BYTES` (1 MiB), checked before parsing and before authentication | `BodyLimit` (**P2.5**) |
| Statement time | `DB_STATEMENT_TIMEOUT_MS` (30 s), on every connection | PostgreSQL (**P2.5**) |
| Rows per user | 100 documents, 100 companies, 200 scenarios; bounded text fields | Quotas (**P2.5** for companies and scenarios) |

**Compression and amplification.** These were tested:
- a 50 MB flate bomb;
- 400 pages sharing one compressed content stream (a few KB on disk, megabytes of text);
- 50k–300k objects;
- deep nesting.

Each ended in a bounded rejection: document FAILED with a user-safe reason. None hung, and none
crashed the worker. The upload size limit alone would not stop these; the text, page and object
limits do.

## 8. Temporary files, filenames, commands

**Temporary files:**
- Each attempt gets a `tempfile.TemporaryDirectory` (unique name, mode `0700`), and the file
  inside it always has the fixed name `document.pdf`.
- The parser's own directory holds only `result`.
- No path comes from user input.
- Both directories are removed after success, rejection and timeout. This is tested by recording
  every directory created during the job.

**Filenames** are display text only:
- NFKC-normalized, last path component only, no control or format characters, at most 255
  characters shown;
- never used as a path, storage key, SQL identifier or command argument;
- the key is `uploads/<32 random URL-safe characters>.pdf`.

Tested with:
- path traversal (`../`, `..\`, absolute paths, `%2e%2e%2f`);
- NUL, CR/LF and quotes;
- `<script>` and a right-to-left override;
- 990-character names.

Duplicate filenames get distinct objects.

**Commands:**
- Nothing in the app runs a command except the sandbox, with the fixed `argv`
  `python -I -B -c <constant> <app dir> <result path>`.
- No shell is involved, and the PDF path travels on stdin.
- No CLI PDF tools are used (Ghostscript, ImageMagick, qpdf, mutool, pdftotext).

## 9. Embedded content

**What is extracted:**
- text;
- table cells;
- page labels and sizes;
- the *list* of images, used only to mark scanned pages as partial.

**What is never touched:**
- JavaScript: PyMuPDF does not run PDF JavaScript on open, and the app never enables it;
- links, launch actions and remote references are never followed;
- embedded files and attachments are never extracted;
- annotations, forms and multimedia are never rendered;
- images are never decoded;
- document metadata (author, producer, XMP) is neither read nor stored.

Fonts are parsed, because text extraction needs them.

## 10. Financial-data integrity

**Provenance chain:** fact → evidence → page / section / chunk → document, enforced by the
database.
- Composite foreign keys (`(evidence_id, document_id)`, `(page_id, document_id)`, …) make a fact
  pointing at another document's evidence impossible.
- Every fact keeps `original_text`, scale, currency, period, confidence, `extraction_method` and
  review reasons.

**No silent overwrite:**
- `_store` replaces a document's results in **one transaction**.
- A failed or timed-out extraction leaves the document FAILED with no partial facts.

**Corrections:**
- A correction sets `extraction_method = manual` and status `corrected`.
- The original value stays in `extraction_reviews`.
- No endpoint modifies evidence.
- Corrected values are bounded to 30 digits with 6 decimal places (**P2.5**).

**Missing ≠ zero** (AGENTS.md rule 18). Scenarios used to treat a missing net income as 0, and a
zero revenue as a 0 margin. They now answer `422 missing_base_fact` / `undefined_margin`
(**P2.5**, tested). The other states stay distinct:

| State | How it shows |
|---|---|
| not found | no fact |
| unreadable | page `extraction_status` is `failed` or `partial` |
| rejected | status `rejected` |
| zero | a fact whose value is 0 |

**Cross-session.** Every read of facts, evidence or calculations goes through `_owned_document`.
Evidence also requires the `(document, evidence)` pair to match. Tested by the P1.5 authorization
matrix and the P2 suite.

## 11. Retention

| Data | Retention | Mechanism |
|---|---|---|
| Verified PDF | `DOCUMENT_RETENTION_DAYS` (30) | Worker sweep; bucket lifecycle at 31 days as a backstop |
| Unverified upload | 1 day | Bucket lifecycle + sweep of abandoned intents |
| Failed document row | `FAILED_DOCUMENT_RETENTION_HOURS` (24) | Sweep; its file is deleted when it fails |
| Text, facts, evidence, calculations, reviews, issues, scenarios | With the document | `ON DELETE CASCADE` |
| Audit events that copied document content | With the document | `remove_document` (**P2.5**) |
| Metadata-only audit/security events | With the workspace | Workspace expiry deletes the user |
| Anonymous workspace | `WORKSPACE_GRACE_HOURS` (24) after the last usable session | Sweep |
| Exports | Not stored | – |
| Temporary files | End of each attempt | `TemporaryDirectory` |
| Orphan objects | `RECONCILE_ORPHAN_GRACE_HOURS` (48), known prefixes only | Daily reconciliation |
| Rate-limit counters | Their window | Sweep |
| Application logs (metadata only) | **Set at the platform** (e.g. 30 days) | Railway/Render/Vercel |
| Database backups | ≤ `DOCUMENT_RETENTION_DAYS` + 7 | Provider PITR setting (§16) |

## 12. Deletion

`DELETE /documents/{id}`, retention and workspace expiry all run `remove_document`:
1. Delete the stored object.
2. Delete the audit rows that copied its content: filenames, before/after values, scenario
   results and reasons (**P2.5**).
3. Delete the document row. This cascades to:
   - pages, sections, chunks and evidence;
   - facts and calculations;
   - jobs, reviews, quality issues and comparisons;
   - **every scenario built from its facts**.

Before P2.5, a scenario created from a company kept copied values after its source document was
deleted. Scenarios now always record their source document.

**Tested:** after deletion, each of these answers 404:
- the document;
- its download URL;
- its evidence;
- its export;
- its fact history;
- its scenario.

The audit trail keeps no copied value or filename. The metadata-only `document_created` and
`document_deleted` events remain as the security record.

**Not claimed:** cryptographic erasure. Deleted data persists in provider backups until they
expire (§16), and in R2 until R2 purges it.

## 13. Object storage

| Property | Status |
|---|---|
| Private bucket; no public access; no listing | Configure it (DEPLOYMENT §2). Verified only by the opt-in real-R2 test `test_bucket_is_private_and_not_listable`, **not run yet** |
| Server-generated keys | Enforced: clients cannot name a key (`extra="forbid"`, tested) |
| Signed URLs: `SIGNED_URL_TTL_SECONDS` (900), one method, one key, exact length, content type, SHA-256 | Signed by the API. Whether R2 enforces expiry, tampering, wrong method, wrong key and wrong body is covered by opt-in real-R2 tests only, **not run yet** |
| Lifecycle rules | `python -m app.storage lifecycle`, applied once |
| Authorization | Always the API's ownership check before a URL is issued. Keys are random and owner-independent: nothing relies on path secrecy |

## 14. Database resource protection

- **Statement timeout:** 30 s on every connection (tested). Migrations use their own engine and
  are unaffected.
- **Pagination and caps:**
  - facts are paged;
  - lists are capped: 100 documents, 200 review items, 200 audit events;
  - company-scope and export loads are refused above `FINANCIALS_MAX_*` / `EXPORT_MAX_*`, never
    truncated.
- **Row caps per user:** documents, companies and scenarios.
- **Connections:** SQLAlchemy's default pool is 5 + 10 per process. Set a per-role
  `CONNECTION LIMIT`.
- **SQL:** no raw SQL is built from user input; `text()` holds only fixed statements.

## 15. Secret rotation (no downtime)

| Secret | Procedure |
|---|---|
| Storage token | Create a new token → set it on the API and worker → redeploy both → verify an upload, a download and a processing run → revoke the old token |
| Database role password | Create `prospect_api_2` in the group → switch the service's `DATABASE_URL` → redeploy → verify → `DROP ROLE` the old one. (`ALTER ROLE … PASSWORD` also works; pooled connections keep working until they recycle.) |
| `APP_SECRET` | Set the new value → redeploy the API. **Every session ends**: users start a new workspace, and old ones expire after the grace period. Do this only on compromise |
| `TRUSTED_PROXY_SECRET` | Update it on the API **and** Vercel, and redeploy both close together. In between, IPs fall back to the proxy's (stricter limits, no outage) |
| Owner credential | Rotate at the provider; only the deploy step uses it |

After any rotation, watch the logs for authentication errors for 24 h.

## 16. Backups and restore

**Not configured yet** (DEPLOYMENT §8). Requirements:
- **Backup mechanism:** provider-managed PITR, encrypted at rest by the provider, reachable only
  through the provider's console and API.
- **Retention:** at most `DOCUMENT_RETENTION_DAYS` + 7. Longer, and backups become where deleted
  documents live on.
- **No exports:** never export backups to personal machines or public buckets.
- **Access:** named people only, with MFA.
- **Stored files:** they are **not** backed up. A lost bucket means users upload again, which is
  acceptable for a temporary workspace.

**Restore test, quarterly:**
1. Restore to a new instance.
2. Run `alembic upgrade head`.
3. Run `python -m app.reconcile` (a dry run) against the real bucket.
4. Check that the missing objects it reports are the expected ones.
5. Destroy the instance.

A backup that has never been restored is not verified.

**Migrations:** each one has a `downgrade`, and CI runs `downgrade base`. After a bad deploy,
prefer restoring PITR to just before the migration over a destructive downgrade.

## 17. Environments and containers

**Environment separation.** Development, test, staging and production each need their own:
- database;
- bucket;
- storage token;
- `APP_SECRET`;
- proxy secret.

**What configuration enforces:** tests default to `ENVIRONMENT=test` with placeholders, and
production refuses placeholder secrets, `http` storage, missing retention, and so on.

**What it cannot catch:** staging pointing at the production database or bucket. That is a
provisioning rule: use distinct names, and never copy production variables into another
environment.

**Containers:** the repo ships no Dockerfile, and Docker is not a deployment requirement. If the
platform builds a container, it must have:
- a non-root user;
- a minimal base image;
- a read-only root with a writable temporary directory only;
- all Linux capabilities dropped and the default seccomp profile;
- memory and CPU limits;
- a health check.

A container alone is not a sandbox.

## 18. Security headers

Verified by tests in `test_security_p1.py` and `apps/web/lib/csp.test.ts`.

| Header | Pages (Vercel) | API | Attacker-influenced? |
|---|---|---|---|
| CSP | Per-request nonce: `script-src 'self' 'nonce-…' 'strict-dynamic'`, `object-src 'none'`, `frame-ancestors 'none'`, `base-uri 'self'`, `form-action 'self'`, `connect-src 'self' <storage origin>` | `default-src 'none'; frame-ancestors 'none'` | No: built from configuration only |
| HSTS | Production | Production | No |
| `nosniff` | ✓ | ✓ | No |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | `no-referrer` | No |
| `Permissions-Policy` | camera, microphone, geolocation, payment off | Same | No |
| COOP | `same-origin` | – (JSON) | No |
| CORP | – | `same-origin` | No |

The storage origin in `connect-src` is required for the direct upload, and it is the only extra
origin allowed.

## 19. CI/CD, dependencies, monitoring

**CI:**
- `permissions: contents: read`;
- no repository secrets, so fork pull requests get nothing;
- `pull_request`, never `pull_request_target`;
- no event data interpolated into a shell;
- actions pinned to commit SHAs;
- the Postgres service image pinned by digest (**P2.5**);
- gitleaks built at a pinned version;
- no build artifacts uploaded.

**Still to set on GitHub:** branch protection on `main` (CI required, no force push, review
required). Deploys go through the platforms' Git integrations, not CI.

**Dependencies:**
- pip-audit and npm audit (production and dev) report 0 known vulnerabilities.
- Lockfiles are committed, and CI installs with `--frozen` / `npm ci`.
- PyMuPDF is the highest-risk dependency: native code parsing hostile input. Track MuPDF security
  releases and keep it current.

**Monitoring.** Every signal below is already emitted as a structured `prospect.security` event
or log line. Alert on them at the log platform. Abuse is identified by IP, session and user id
only; there is no fingerprinting or behavioural tracking.

| Signal | Event / source | Suggested alert |
|---|---|---|
| Uploads rejected (size, type, checksum, malware) | `upload_rejected_*`, `upload_checksum_mismatch` | > 20/h |
| Processing failures, timeouts, resource limits | `processing_timeout`, `processing_resource_limit`, audit `processing_failed` | > 10/h or a spike |
| Parser without network isolation | log `parser runs without network isolation` | any, in production |
| Parser output refused | log `parser output refused` | **any**: possible exploit attempt |
| Quota and rate-limit violations | `quota_exceeded`, `rate_limit_exceeded` | > 100/h from one IP |
| Cross-session attempts | `authorization_denied` | > 20/h from one session |
| CSRF failures | `csrf_rejected` | spike |
| Unusual session creation | `rate_limit_exceeded`, bucket `sessions_daily` | any |
| Storage or database failures | 503 responses, `dependency unavailable` | > 1% of requests |
| Mass export | audit `export_created` | > 50/h per user |
| Missing objects | `object_missing` | any |

## 20. Remaining risks (not solvable inside the repository)

| Risk | Why | Next step |
|---|---|---|
| **Parser code-execution isolation** | The parser shares the OS user, kernel and filesystem with the worker, and network isolation depends on the host allowing user namespaces | A separate parse runtime (gVisor, Firecracker, or a credential-less container with no egress); `PROCESSING_NETWORK_ISOLATION=required` once verified |
| **API/worker compromise** | Both hold DML over all rows and a token for the whole bucket; authorization lives in application code | Separate storage tokens per service; row-level security would be a redesign |
| **Cloud configuration** | These are platform settings, outside the code: bucket privacy, CORS, lifecycle, token scope, DB roles, PITR, egress rules, branch protection | DEPLOYMENT §9 and this document; run `tests/integration/test_r2.py` against staging |
| **Storage provider behaviour** | R2's enforcement of checksum, length, expiry and method has never been observed | Run the opt-in R2 suite and record the result |
| **Backups** | None exist, and no restore has ever been done | Enable PITR, set its retention, do the first restore test |
| **Incident response** | A document ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)), not a practised process | Assign owners and rehearse once |
