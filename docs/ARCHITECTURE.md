# Prospect System Architecture

## 1. Architecture Goal

Prospect is a real public web application.

The architecture prioritizes:

- simple managed deployment;
- low operational overhead;
- clear service boundaries;
- asynchronous document processing;
- evidence-first financial data;
- replaceable AI providers.

Docker is optional for local development and is NOT a production deployment dependency.

## 2. Production Architecture

```text
                         PUBLIC INTERNET
                               │
                               ▼
                    ┌─────────────────────┐
                    │       Vercel        │
                    │ Next.js Web App     │
                    └──────────┬──────────┘
                               │ HTTPS
                               ▼
                    ┌─────────────────────┐
                    │ API service         │
                    │ FastAPI             │
                    │ Vercel (/api/v1)    │
                    └──────┬───────┬──────┘
                           │       │
                           │       ▼
                           │  ┌──────────────┐
                           │  │ AI Provider  │
                           │  │ LLM/Embed    │
                           │  └──────────────┘
                           │
                ┌──────────┴──────────┐
                ▼                     ▼
       ┌────────────────┐    ┌──────────────────┐
       │ Managed        │    │ Private Object   │
       │ PostgreSQL     │    │ Storage          │
       │ + pgvector     │    │ R2 / Supabase    │
       └────────────────┘    └──────────────────┘
                ▲                     ▲
                │                     │
                └──────────┬──────────┘
                           │
                  ┌────────▼────────┐
                  │ Managed Worker  │
                  │ Railway/Render  │
                  └─────────────────┘
```

## 3. Recommended Deployment

### Frontend

**Vercel**

Responsibilities:

- Next.js application
- public website
- authenticated UI
- document workspace
- research interface

### Backend API

**Vercel**, as the `api` service of the same project (docs/ADR-006)

Responsibilities:

- FastAPI
- authentication
- authorization
- document metadata
- signed upload URLs
- research orchestration
- calculations
- API endpoints

### Worker

**Railway or Render**

Responsibilities:

- PDF processing
- text extraction
- table extraction
- OCR fallback
- financial extraction
- chunking
- embeddings
- indexing

The worker should be independently deployable from the API.

### Database

**Managed PostgreSQL**

Recommended options:

- Railway PostgreSQL
- Supabase PostgreSQL

Requirements:

- PostgreSQL
- NUMERIC/DECIMAL
- pgvector support
- automated backups where available

### Object Storage

Recommended:

- Cloudflare R2
- Supabase Storage

Requirements:

- private buckets
- server-side credentials
- signed URLs for controlled access
- lifecycle/deletion support

## 4. Production Request Flow

### Normal API request

```text
Browser
 ↓
Vercel
 ↓
FastAPI
 ↓
PostgreSQL
 ↓
Response
```

### PDF upload

Prefer direct-to-object-storage upload:

```text
Browser
 ↓
FastAPI requests signed upload URL
 ↓
Browser uploads PDF directly to Object Storage
 ↓
Browser tells API upload is complete
 ↓
API creates processing job
 ↓
Worker processes document
```

This avoids routing large PDFs through the API server.

## 5. Processing Flow

```text
Object Storage
      ↓
Job Queue / Worker Trigger
      ↓
Worker
      ↓
PDF Parser
      ↓
Text / Table Extraction
      ↓
Financial Extraction
      ↓
Evidence Creation
      ↓
Database
      ↓
Embeddings
      ↓
READY
```

For the first deployment, a simple database-backed job queue or managed worker mechanism is acceptable. A dedicated Redis queue can be introduced later if required.

## 6. Local Development

Docker is optional.

Preferred minimum local setup:

```text
Node.js
Python
PostgreSQL
```

Developers may use hosted development services for PostgreSQL and object storage.

Docker Compose may be provided as an optional convenience, but no production feature may depend on Docker.

## 7. Environment Variables

Frontend (server-side only; on Vercel `/api/v1` is routed to the API service, elsewhere proxied
to `API_ORIGIN`):

```text
API_ORIGIN
STORAGE_ORIGIN
```

Backend:

```text
DATABASE_URL
OBJECT_STORAGE_ENDPOINT
OBJECT_STORAGE_BUCKET
OBJECT_STORAGE_ACCESS_KEY
OBJECT_STORAGE_SECRET_KEY
LLM_API_KEY
EMBEDDING_API_KEY
APP_SECRET
ALLOWED_ORIGINS
DOCUMENT_SCANNER
```

Worker:

```text
DATABASE_URL
OBJECT_STORAGE_ENDPOINT
OBJECT_STORAGE_BUCKET
OBJECT_STORAGE_ACCESS_KEY
OBJECT_STORAGE_SECRET_KEY
LLM_API_KEY
EMBEDDING_API_KEY
```

Never expose server secrets through `NEXT_PUBLIC_*`.

## 8. CORS

Production API should allow only the deployed frontend origin.

Example:

```text
https://prospect.example.com
```

Development can allow localhost origins.

## 9. Health Checks

API:

```text
GET /health
```

Worker should expose a platform-compatible health mechanism or heartbeat.

Health checks must not perform expensive document processing.

## 10. Observability

At minimum log:

- request ID
- document ID
- job ID
- processing stage
- duration
- errors
- AI provider errors

Production should expose:

- application logs
- worker logs
- database metrics where available
- uptime/health monitoring

## 11. Scaling

Initial:

```text
1 frontend
1 API instance
1 worker
1 managed PostgreSQL
1 object store
```

Scale workers independently as document volume grows.

Do not prematurely introduce Kubernetes or microservices.

## 12. Security

- private object storage
- signed URLs
- authentication
- document ownership checks
- rate limiting
- file type validation
- file size limits
- secret management
- HTTPS
- database least-privilege credentials

## 13. Architecture Principle

Keep this boundary:

```text
Web UI
   ↓
API
   ↓
Domain / Data
   ↓
Worker / Evidence
   ↓
AI
```

AI must remain replaceable.
