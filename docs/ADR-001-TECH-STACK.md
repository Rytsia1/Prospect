# ADR-001: Initial Technical Stack

## Status

Accepted

## Context

Prospect requires PDF processing, financial data handling, relational storage, vector retrieval, and a web research interface.

## Decision

Use:

- Next.js + TypeScript for web
- FastAPI + Python for API/domain services
- Python workers for document processing
- PostgreSQL for relational storage
- pgvector for embeddings
- S3-compatible object storage for PDFs
- Docker for local reproducibility

## Alternatives Considered

### Spring Boot

Strong backend option and familiar for enterprise applications, but Python provides a more convenient ecosystem for PDF, OCR, table extraction, and NLP work.

### Separate Vector Database

Deferred. pgvector keeps the MVP operationally simpler.

## Consequences

Positive:

- strong document-processing ecosystem
- clear separation between frontend and processing
- relational + vector search in one database
- portable deployment

Negative:

- multiple languages/runtime concerns are possible if other services are added
- Python service requires careful domain typing and testing
