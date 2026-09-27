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

Run migrations.

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
APP_SECRET          # ≥ 32 random bytes; startup fails on a weak or placeholder value
ALLOWED_ORIGINS     # https://prospect.example.com (the web app only; CORS + CSRF)
DOCUMENT_SCANNER    # clamav (recommended) or none; startup fails if unset
CLAMAV_HOST / CLAMAV_PORT
DOCUMENT_RETENTION_DAYS           # optional; unset keeps documents until the user deletes them
FORWARDED_ALLOW_IPS # "*" only if the API is reachable solely through the platform proxy
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

The worker must use the same database and object-storage credentials.

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
