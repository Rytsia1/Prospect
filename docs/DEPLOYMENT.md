# Prospect Web Deployment Specification

## 1. Production Goal

Deploy Prospect as a publicly accessible website without requiring Docker.

Target:

```text
https://prospect.<domain>
```

## 2. Recommended Stack

| Component | Provider | Purpose |
|---|---|---|
| Frontend | Vercel | Next.js |
| API | Railway / Render | FastAPI |
| Worker | Railway / Render | PDF processing |
| Database | Railway PostgreSQL / Supabase | PostgreSQL + pgvector |
| File storage | Cloudflare R2 / Supabase Storage | Private PDFs |
| Domain | DNS provider | Custom domain |
| AI | LLM provider | Research + extraction |
| Monitoring | Platform + optional external monitor | Availability/logs |

## 3. Deployment Sequence

### Step 1 — Database

Create managed PostgreSQL.

Enable:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

Run migrations, as the database owner, from the deploy step only.

Then create the least-privilege service roles (`apps/api/deploy/db_roles.sql`, as the owner):
one `LOGIN` role per service in the `prospect_app` group, each with its own generated password.
The API and the worker get their own `DATABASE_URL` with their own role; neither gets the owner.
Set a connection limit per role (`ALTER ROLE … CONNECTION LIMIT n`) sized to the service's pool
(SQLAlchemy default: 5 + 10 overflow per process).

### Step 2 — Object Storage

Create a private bucket:

```text
prospect-documents
```

Do not make the bucket public.

### Step 3 — API

Deploy FastAPI to Railway or Render.

Configure:

```text
ENVIRONMENT=production
DATABASE_URL
OBJECT_STORAGE_*
LLM_API_KEY
APP_SECRET            # ≥ 32 random bytes; the API refuses to start without it
TRUSTED_PROXY_SECRET  # ≥ 32 random bytes; the same value on Vercel; required
ALLOWED_ORIGINS       # https://prospect.example.com (the web app only; CORS + CSRF)
DOCUMENT_SCANNER      # clamav (recommended) or none; startup fails if unset
DOCUMENT_RETENTION_DAYS=30
```

Start command (no forwarded-header trust: client IPs come only from the web proxy):

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log --no-proxy-headers
```

Once per bucket, with credentials allowed to configure it, apply the storage lifecycle rules
(abandoned uploads expire after a day even if the worker never runs):

```bash
python -m app.storage lifecycle
```

The bucket's CORS rule must allow `PUT` from the web origin with the headers `Content-Type` and
`x-amz-checksum-sha256`.

Limits, quotas and rate limits have safe defaults; see docs/SECURITY.md to tune them.

Deploy migrations.

Verify:

```text
GET /health
```

### Step 4 — Worker

Deploy the document-processing worker.

The worker must use the same database and object-storage credentials, and must NOT be given
`APP_SECRET` or `TRUSTED_PROXY_SECRET` (it needs neither and warns if it holds `APP_SECRET`).
Also set `CLAMAV_HOST`/`CLAMAV_PORT`, a service memory limit, and a non-root user
(docs/SECURITY.md §15). Give it its own database role (Step 1) and its own storage token.

Parser isolation (docs/SECURITY_P2_5.md §4): the parser child runs without any secret already.
Check the worker's log for `parser runs without network isolation`. If it appears, the host
blocks unprivileged user namespaces; either allow them (then set
`PROCESSING_NETWORK_ISOLATION=required`) or restrict the worker's egress at the platform to the
database, storage and clamd hosts.

Verify:

- worker starts
- worker can read a document
- worker can write evidence
- worker can update job status

### Step 5 — Frontend

Deploy Next.js to Vercel.

Configure:

```text
API_ORIGIN=https://api.example.com          # /api/v1 is proxied here (set before building)
STORAGE_ORIGIN=https://<account-id>.r2.cloudflarestorage.com
TRUSTED_PROXY_SECRET=<same value as the API> # the build fails on Vercel without it
```

### Step 6 — Custom Domain

Configure:

```text
prospect.example.com
api.example.com
```

Vercel handles the frontend domain.

Railway/Render handles the API domain.

### Step 7 — Production CORS

Set:

```text
ALLOWED_ORIGINS=https://prospect.example.com
```

`*` is refused at startup. Browsers use the same-origin proxy, so CORS never carries
credentials; it only serves Bearer-token clients on a trusted origin.

## 4. Upload Architecture

Do not upload large PDFs through the API if avoidable.

Preferred:

```text
Browser
 ↓
POST /documents/upload-url
 ↓
Signed upload URL
 ↓
Object Storage
 ↓
POST /documents/{id}/complete
 ↓
Worker
```

## 5. Worker Trigger

Initial implementation options:

### Option A — Database Job Polling

```text
API inserts job
 ↓
Worker polls jobs table
 ↓
Worker claims job
 ↓
Worker processes
```

Simple and adequate for MVP.

### Option B — Redis Queue

Introduce when job volume requires it.

Do not add Redis solely for architectural aesthetics.

## 6. Deployment Environments

At minimum:

```text
development
production
```

Optional:

```text
preview
staging
```

Vercel preview deployments can be used for frontend changes.

## 7. Production Checklist

### Frontend

- [ ] deployed
- [ ] HTTPS active
- [ ] environment variables configured
- [ ] `API_ORIGIN` and `STORAGE_ORIGIN` set before the build
- [ ] production build succeeds
- [ ] pages send Content-Security-Policy with a nonce and no console CSP violations

### API

- [ ] deployed
- [ ] `/health` works
- [ ] migrations applied
- [ ] `ALLOWED_ORIGINS` = the web origin only (https)
- [ ] `DOCUMENT_SCANNER` chosen explicitly (clamav, or none accepted knowingly)
- [ ] /docs and /openapi.json answer 404
- [ ] secrets configured
- [ ] `ENVIRONMENT=production` and a generated `APP_SECRET` (startup refuses weak secrets)
- [ ] rate limits answer 429 with `Retry-After` (docs/SECURITY.md §6)
- [ ] logs available

### Worker

- [ ] deployed
- [ ] can connect to DB
- [ ] can access object storage
- [ ] processes test PDF
- [ ] failure state works
- [ ] clamd reachable, `StreamMaxLength` ≥ `MAX_UPLOAD_BYTES` (if DOCUMENT_SCANNER=clamav)
- [ ] service memory limit set (second boundary around the parser child processes)

### Database

- [ ] pgvector enabled
- [ ] migrations applied
- [ ] backups enabled if provider supports them

### Storage

- [ ] bucket private
- [ ] lifecycle rules applied (`python -m app.storage lifecycle`)
- [ ] bucket CORS allows PUT with Content-Type and x-amz-checksum-sha256 from the web origin only
- [ ] upload works
- [ ] download via signed URL works
- [ ] deletion works

### End-to-End

- [ ] user opens website
- [ ] uploads PDF
- [ ] processing begins
- [ ] processing finishes
- [ ] financial fact appears
- [ ] page evidence opens
- [ ] calculation appears
- [ ] research query works

## 8. Backups and Recovery

Nothing here exists until it is configured on the hosting platforms; PostgreSQL running is not a
backup.

**Database (holds everything except the PDFs).**

- Strategy: the managed provider's automated daily backups plus point-in-time recovery (Railway,
  Render, Neon and Supabase all offer it on paid plans; enable it explicitly).
- Retention: at least 7 days of PITR. Keep it no longer than `DOCUMENT_RETENTION_DAYS` + 7:
  backups also contain deleted workspaces, so they extend how long HIGH data lives (a restore
  brings deleted documents' rows back; the sweep and retention delete them again once running).
- Restore: restore into a new database, run `alembic upgrade head`, point `DATABASE_URL` of the
  API and worker at it, then run `python -m app.reconcile` (dry run) to list documents whose
  files are gone (expected: storage is not rolled back).
- Verify quarterly: restore the latest backup into a scratch database, run `alembic current`
  (must be head) and `select count(*) from documents`, and `python -m app.reconcile` against a
  copy of the settings. Record the date and result.

**Object storage (PDFs).** Not backed up, deliberately: documents are temporary by design
(docs/SECURITY.md §2), re-uploadable by their owner, and a backup would keep HIGH data past its
retention. Expectation: after a storage loss, affected documents fail with "The uploaded file is
missing"; users upload again. Their extracted facts survive only until those documents are
deleted.

**Not configured yet (to do before launch):** enable PITR on the database; decide backup
retention; run and record a first restore test; store the restore runbook next to the incident
contacts.

## 9. Production Configuration Checklist

Enforced at startup (the API or worker refuses to start): `ENVIRONMENT` defaults to production;
`APP_SECRET` present (API) and strong; `TRUSTED_PROXY_SECRET` present (API) and strong;
`ALLOWED_ORIGINS` exact https origins; secure session cookie; `DOCUMENT_SCANNER` chosen;
`DOCUMENT_RETENTION_DAYS` set; https storage endpoint; rate limits well formed; lease longer than
the processing timeout. Enforced on Vercel builds: `API_ORIGIN` and `TRUSTED_PROXY_SECRET`.

By hand: HTTPS on every domain; private bucket; bucket CORS and lifecycle rules; upload, processing
and quota limits reviewed for expected traffic (defaults in docs/SECURITY.md); uvicorn started
with `--no-proxy-headers`; database backups (§8); worker user and memory limit.
