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
- Node.js 22+ and npm
- PostgreSQL 15+ with the `pgvector` extension available. A local install or a hosted
  development database (Railway, Supabase) both work.
- An S3-compatible private bucket (Cloudflare R2 in production). Only needed once document
  upload lands; the API starts and tests pass with placeholder values.

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

Database constraint tests run when `TEST_DATABASE_URL` points to a migrated database:

```bash
TEST_DATABASE_URL=postgresql://... uv run pytest
```

```bash
cd apps/web
npm run lint && npm run typecheck && npm run build
```

CI (`.github/workflows/ci.yml`) runs all of the above against PostgreSQL + pgvector.

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
