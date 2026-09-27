# Prospect — Pre-Coding Specification

Prospect is an evidence-first financial document intelligence platform intended to be deployed as a real public website.

## Production Deployment

```text
Next.js
  → Vercel

FastAPI
  → Railway / Render

Worker
  → Railway / Render

PostgreSQL + pgvector
  → Railway / Supabase

Private PDF storage
  → Cloudflare R2 / Supabase Storage
```

**Docker is optional and is not required for local development or production deployment.**

## Repository Layout

```text
apps/api     FastAPI service: config, models, migrations, object storage, tests
apps/web     Next.js + TypeScript + Tailwind web app
docs/        Specifications and ADRs (source of truth)
```

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22.18+ (24 recommended) and npm
- PostgreSQL 15+ with the `pgvector` extension available. A local install or a hosted
  development database (Railway, Supabase) both work.
- An S3-compatible private bucket: Cloudflare R2 in production. For local development either
  use an R2 dev bucket or run the in-process S3 emulator that ships with the dev dependencies
  (see "Local object storage").

## Environment Variables

API (`apps/api/.env`, copied from `apps/api/.env.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL URL; `postgres://` and `postgresql://` forms are accepted |
| `OBJECT_STORAGE_ENDPOINT` | S3-compatible endpoint, e.g. `https://<account>.r2.cloudflarestorage.com` |
| `OBJECT_STORAGE_BUCKET` | Private bucket name |
| `OBJECT_STORAGE_ACCESS_KEY` / `OBJECT_STORAGE_SECRET_KEY` | Bucket credentials |
| `APP_SECRET` | Application signing secret (long random string) |
| `CORS_ORIGINS` | Comma-separated allowed origins; production = the Vercel domain only |
| `LOG_LEVEL` | Optional, default `INFO` |
| `MAX_UPLOAD_BYTES` | Optional upload limit, default 52428800 (50 MB) |

Web (`apps/web/.env.local`, copied from `apps/web/.env.example`):

| Variable | Purpose |
|---|---|
| `NEXT_PUBLIC_API_URL` | Public URL of the API |
| `NEXT_PUBLIC_APP_URL` | Public URL of the web app |

`.env` files are git-ignored. Production values belong in the Vercel / Railway / Render
environment settings. Never put server secrets in `NEXT_PUBLIC_*` variables.

## Run the Backend

```bash
cd apps/api
cp .env.example .env                    # then edit DATABASE_URL etc.
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload    # http://localhost:8000/health
```

Production start command (Railway/Render):
`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT --no-access-log`

Security controls (sessions, rate limits, upload limits, processing sandbox, quotas, export
limits) and the production environment variables are described in
[docs/SECURITY.md](docs/SECURITY.md). Set `ENVIRONMENT=production` and a strong `APP_SECRET` in
production: the API and worker refuse to start otherwise.

## Run the Document Worker

The worker turns uploaded PDFs into pages, sections, and chunks. It polls the
`processing_jobs` table, so it needs the same environment variables as the API.

```bash
cd apps/api
uv run python -m app.worker
```

Deploy it as a second Railway/Render service from `apps/api` with start command
`python -m app.worker` (no migrations; the API service runs them). When the platform sets
`PORT`, the worker answers `GET /health` on it.

Behavior: failed jobs caused by the document itself (damaged, password-protected, no text
layer) fail immediately with a user-visible reason. Other errors retry up to 3 times with
backoff. A job whose worker died is reclaimed after a 15-minute lease, so documents never stay
in PROCESSING. Reprocessing replaces a document's pages/sections/chunks in one transaction.

Financial facts (revenue, gross profit, operating income, net income, total assets,
current assets, total liabilities, current liabilities, equity, cash, total debt) are extracted deterministically in the same
transaction, without an LLM (`app/extraction.py`). Each fact stores its value as NUMERIC, its
period type, currency and scale, the value as printed, and evidence pointing to the exact row,
page, section and chunk. Values whose currency, scale or period is not stated, or that conflict
across pages, are kept as `needs_review` and are not shown as facts.

Ratios (revenue growth, net margin, ROA, ROE, debt-to-equity, current ratio) are then computed
from the accepted facts in the same transaction by `app/analytics.py`: Decimal only, in a fixed
context, no LLM. Each result stores its formula and input facts, so every ratio leads back to
the source pages. A missing input, zero denominator, or mismatched currency/period is stored as
`not_possible` with a reason, never as zero. Rounding happens only in the UI.

The research workspace (Overview, Financials, Timeline, Evidence, Reconciliation, Export) is
derived on read from the same facts (`app/workspace.py`, `app/financials.py`): nothing is copied
into view tables. Reports that share a company name form a company timeline; a value repeated as a
comparative in a later report is shown once, and values that disagree are shown as conflicts,
never overwritten. Exports (CSV, JSON, XLSX) serialize that same payload with exact decimals; XLSX
is written with the standard library, so no spreadsheet dependency is added. Balance-sheet
reconciliation tolerance is configurable with `RECONCILIATION_ROUNDING_UNITS` (default 3) and
`RECONCILIATION_RELATIVE_TOLERANCE` (default 0.0001).

PDF parsing uses PyMuPDF, which is licensed AGPL-3.0 (commercial licenses are available from
Artifex). Running it in a public web service carries AGPL obligations; review before launch.

## Object Storage (Cloudflare R2)

The bucket must stay private: no public access, no r2.dev URL. The API holds the credentials
and hands the browser short-lived (15 minute) signed URLs; the browser PUTs the PDF straight to
R2, then the API verifies the stored bytes (size + PDF signature) before accepting it.

The browser upload needs a CORS rule on the bucket (R2 → bucket → Settings → CORS policy):

```json
[
  {
    "AllowedOrigins": ["https://prospect.example.com"],
    "AllowedMethods": ["PUT", "GET"],
    "AllowedHeaders": ["Content-Type"],
    "MaxAgeSeconds": 3600
  }
]
```

Add `http://localhost:3000` to `AllowedOrigins` on a development bucket.

### Local object storage

Without an R2 dev bucket, run the S3 emulator from the API dev dependencies (moto):

```bash
cd apps/api
uv run moto_server -H 127.0.0.1 -p 9000
uv run python -c "import boto3; boto3.client('s3', endpoint_url='http://127.0.0.1:9000', aws_access_key_id='local', aws_secret_access_key='local', region_name='us-east-1').create_bucket(Bucket='prospect-documents')"
```

Then set `OBJECT_STORAGE_ENDPOINT=http://127.0.0.1:9000` and any non-empty access/secret keys.
Data is in memory and lost when the emulator stops; it does not enforce access control, so it
cannot demonstrate bucket privacy (R2 does).

## Run the Frontend

```bash
cd apps/web
cp .env.example .env.local
npm install
npm run dev                             # http://localhost:3000
```

## Tests and Checks

```bash
cd apps/api
uv run pytest                           # unit tests
uv run ruff format . && uv run ruff check . && uv run mypy
```

Database and upload-flow tests run when `TEST_DATABASE_URL` points to a migrated database
(they start their own in-process S3 emulator):

```bash
TEST_DATABASE_URL=postgresql://... uv run pytest
```

```bash
cd apps/web
npm run lint && npm run typecheck && npm test && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above against PostgreSQL + pgvector.

## Identity (single-user mode)

Until authentication lands, each browser gets an anonymous identity: `POST /api/v1/sessions`
returns a token signed with `APP_SECRET`, stored in `localStorage` and sent as a bearer token.
Every document query is scoped to that user, so documents are isolated per browser. Clearing
browser storage or rotating `APP_SECRET` loses access to earlier uploads.

## Specification Artifacts

- `PRD.md`
- `docs/MVP_SPEC.md`
- `docs/ARCHITECTURE.md`
- `docs/DATA_MODEL.md`
- `docs/API_SPEC.yaml`
- `docs/FINANCIAL_CALCULATIONS.md`
- `docs/AI_RAG_SPEC.md`
- `docs/UX_SPEC.md`
- `docs/EVALUATION.md`
- `docs/DEPLOYMENT.md`
- `AGENTS.md`
- `docs/ADR-*.md`

## First Vertical Slice

```text
Upload Annual Report
      ↓
Process PDF
      ↓
Extract Revenue
      ↓
Attach Page Evidence
      ↓
Extract Previous-Year Revenue
      ↓
Calculate Revenue Growth
      ↓
Display Fact + Calculation + Source
      ↓
Deploy to public website
```
