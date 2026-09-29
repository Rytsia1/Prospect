# ADR-005: Managed Web Deployment Without Docker

## Status

Accepted; superseded for the API by ADR-006 (the API now runs as a Vercel service next to
the web app). Worker, database and storage decisions stand.

## Context

Prospect is intended to be a publicly accessible portfolio website. The deployment should be simple enough to maintain as a solo project and should not require managing servers or container infrastructure.

## Decision

Use managed services:

- Vercel for Next.js
- Railway or Render for FastAPI
- Railway PostgreSQL or Supabase for PostgreSQL
- Cloudflare R2 or Supabase Storage for private PDF storage
- Railway or Render for the document worker

Docker is optional for local development and is not required in production.

## Alternatives

### Docker on a VPS

Rejected for the initial project because it introduces server maintenance, deployment, SSL, monitoring, and scaling responsibilities that do not contribute directly to the product goal.

### Kubernetes

Rejected as unnecessary operational complexity.

### Serverless-only architecture

Not selected for document processing because PDF/OCR/table extraction may require longer-running workloads.

## Consequences

Positive:

- fast deployment
- public URL
- managed HTTPS
- low infrastructure maintenance
- independent scaling of API and worker
- portfolio-friendly deployment story

Negative:

- provider-specific configuration
- recurring hosted-service costs
- multiple platforms to manage
- platform limits must be understood
