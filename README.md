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
