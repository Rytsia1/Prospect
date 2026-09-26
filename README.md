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

**Docker is not required for production or for users.**

## Local Development

Requires Python 3.12+ with [uv](https://docs.astral.sh/uv/), Node.js 22+, and a PostgreSQL database with pgvector (local or hosted). Docker is not needed.

API (`apps/api`):

```bash
cp .env.example .env        # point DATABASE_URL at your database
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload   # http://localhost:8000/health
uv run pytest
```

Web (`apps/web`):

```bash
cp .env.example .env.local
npm install
npm run dev                            # http://localhost:3000
```

Production start command for the API (Railway/Render):
`alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port $PORT`

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
