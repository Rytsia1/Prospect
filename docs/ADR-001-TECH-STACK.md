# ADR-001: Initial Technical Stack

## Status

Accepted

## Context

Prospect requires PDF processing, financial data handling, relational storage, vector retrieval, and a public web interface.

## Decision

Use:

- Next.js + TypeScript for web
- Vercel for frontend deployment
- FastAPI + Python for API/domain services
- Railway or Render for API deployment
- Python worker on Railway or Render
- PostgreSQL for relational storage
- pgvector for embeddings
- Cloudflare R2 or Supabase Storage for private PDFs
- Docker only as an optional local development convenience

## Alternatives Considered

### Spring Boot

Strong enterprise backend option, but Python has a more convenient ecosystem for PDF, OCR, table extraction, and NLP.

### Dedicated Vector Database

Deferred. pgvector keeps the MVP simpler.

### Docker-based production

Deferred/rejected for the initial deployment because managed application services provide a simpler public deployment path.

## Consequences

Positive:

- practical document-processing ecosystem
- public web deployment
- low operational overhead
- relational and vector storage together
- clear worker boundary

Negative:

- multiple hosted providers may need configuration
- recurring infrastructure costs
- Python service requires careful typing and testing
