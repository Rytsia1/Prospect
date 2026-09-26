# Prospect System Architecture

## 1. Architectural Goal

Build an evidence-first financial document system where AI is a replaceable interpretation layer rather than the source of financial truth.

## 2. Logical Architecture

```text
                    ┌──────────────────────┐
                    │       Next.js        │
                    │ Research Workspace   │
                    └──────────┬───────────┘
                               │ HTTPS
                    ┌──────────▼───────────┐
                    │       FastAPI        │
                    │ API / Domain Layer   │
                    └───────┬─────┬────────┘
                            │     │
                ┌───────────┘     └────────────┐
                ▼                              ▼
        ┌──────────────┐                ┌──────────────┐
        │ PostgreSQL   │                │ Object Store │
        │ + pgvector   │                │ Private PDFs │
        └──────────────┘                └──────────────┘
                ▲
                │
        ┌───────┴────────┐
        │ Processing Job │
        └───────┬────────┘
                ▼
        ┌───────────────┐
        │ Worker        │
        │ PDF / OCR /   │
        │ Table / NLP   │
        └───────┬───────┘
                │
                ▼
        Evidence + Facts
                │
                ▼
        ┌───────────────┐
        │ Research      │
        │ Retrieval     │
        └───────┬───────┘
                ▼
              LLM
```

## 3. Major Components

### Web

Responsibilities:

- upload UI
- processing status
- document workspace
- PDF viewer
- financial overview
- research chat

The web app must not contain financial calculation logic.

### API

Responsibilities:

- authentication/authorization
- document metadata
- API contracts
- domain orchestration
- calculations
- research orchestration

### Worker

Responsibilities:

- download source PDF
- parse pages
- extract text
- extract tables
- detect sections
- normalize financial values
- generate evidence records
- create embeddings

### Database

PostgreSQL stores:

- users
- documents
- pages
- chunks
- sections
- financial facts
- evidence
- calculations
- research sessions

pgvector stores semantic embeddings.

### Object Storage

Stores original PDFs and optionally page/render artifacts.

Files remain private.

## 4. Processing State Machine

```text
UPLOADED
  ↓
QUEUED
  ↓
PROCESSING
  ├──→ FAILED
  │      ↓
  │    RETRY
  ↓
EXTRACTING
  ↓
INDEXING
  ↓
READY
```

## 5. Data Flow

```text
Client
 ↓
API creates document
 ↓
Object storage
 ↓
Queue
 ↓
Worker
 ↓
Parser
 ↓
Raw pages
 ↓
Evidence extraction
 ↓
Financial extraction
 ↓
Validation
 ↓
PostgreSQL
 ↓
Embedding index
 ↓
READY
```

## 6. Architectural Rules

1. Financial values must be represented with decimal-safe types.
2. LLM output must not directly overwrite source facts.
3. Every financial fact requires provenance.
4. Calculations consume structured facts, not generated prose.
5. Retrieval results must retain evidence identity.
6. The frontend never accesses the database directly.
7. Storage URLs are private or signed and time-limited.
8. Long-running work is asynchronous.
9. Provider-specific AI code is isolated behind an interface.
10. All schema changes use migrations.

## 7. Failure Strategy

A worker must distinguish:

- permanent invalid input
- temporary infrastructure failure
- low-confidence extraction
- unsupported document structure

Never silently convert failed extraction into a fabricated value.

## 8. Deployment

Development:

```text
Docker Compose
├── web
├── api
├── worker
├── postgres
└── object storage
```

Production can split services across managed providers while retaining the same logical boundaries.
