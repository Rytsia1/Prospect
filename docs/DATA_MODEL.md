# Prospect Data Model

## 1. Design Principles

- relational source of truth
- explicit provenance
- decimal-safe financial values
- immutable source evidence where practical
- derived calculations reference their inputs
- embeddings are indexes, not canonical data

## 2. Entity Overview

```text
User
 └──< Document
       ├──< DocumentPage
       │     └──< DocumentChunk
       ├──< DocumentSection
       └──< FinancialFact
              └──< Evidence

Calculation
 ├──< CalculationInput >── FinancialFact
 └── result

ResearchSession
 └──< ChatMessage
        └──< ChatCitation >── Evidence
```

## 3. Tables

### users

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| email | VARCHAR | unique, nullable (anonymous single-user-mode sessions) |
| created_at | TIMESTAMP | required |

### documents

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | FK users |
| filename | VARCHAR | original name |
| document_type | ENUM | annual_report, financial_statement, prospectus |
| fiscal_year | INTEGER | nullable |
| mime_type | VARCHAR | required |
| size_bytes | BIGINT | required, > 0; verified against the stored object |
| storage_key | VARCHAR | private object key |
| status | ENUM | UPLOADING, UPLOADED, QUEUED, PROCESSING, EXTRACTING, INDEXING, READY, FAILED |
| processing_error | TEXT | nullable |
| created_at | TIMESTAMP | required |
| updated_at | TIMESTAMP | required |

### processing_jobs

Database-backed job queue polled by the worker (DEPLOYMENT.md §5, option A).

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK documents, cascade |
| status | ENUM | queued/running/succeeded/failed |
| attempts | INTEGER | >= 0 |
| last_error | TEXT | nullable |
| locked_at | TIMESTAMP | nullable; worker claim time |
| created_at | TIMESTAMP | required |
| updated_at | TIMESTAMP | required |

### document_pages

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK |
| page_number | INTEGER | 1-based |
| text | TEXT | extracted text |
| extraction_status | ENUM | success/partial/failed |

Unique:

```text
(document_id, page_number)
```

### document_sections

| Column | Type |
|---|---|
| id | UUID |
| document_id | UUID |
| title | VARCHAR |
| start_page | INTEGER |
| end_page | INTEGER |

### document_chunks

| Column | Type |
|---|---|
| id | UUID |
| page_id | UUID |
| chunk_index | INTEGER |
| content | TEXT |
| embedding | VECTOR |

Unique:

```text
(page_id, chunk_index)
```

### financial_metrics

Metric definitions.

| Column | Type |
|---|---|
| id | UUID |
| key | VARCHAR |
| name | VARCHAR |
| category | VARCHAR |
| description | TEXT |

### financial_facts

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK |
| metric_id | UUID | FK |
| value_numeric | NUMERIC | decimal-safe |
| currency | CHAR(3) | nullable |
| scale | VARCHAR | units/thousands/millions/billions |
| period_start | DATE | nullable |
| period_end | DATE | required |
| period_label | VARCHAR | e.g. FY2025 |
| confidence | NUMERIC(5,4) | 0–1 |
| extraction_method | VARCHAR | parser/llm/ocr/manual |
| created_at | TIMESTAMP | required |

### evidence

| Column | Type |
|---|---|
| id | UUID |
| document_id | UUID |
| page_id | UUID |
| section_id | UUID nullable |
| evidence_type | ENUM |
| content | TEXT |
| bbox_json | JSONB nullable |
| locator | JSONB |
| created_at | TIMESTAMP |

`locator` may contain table/cell coordinates when available.

### calculations

| Column | Type |
|---|---|
| id | UUID |
| document_id | UUID |
| metric_key | VARCHAR |
| formula_key | VARCHAR |
| result_numeric | NUMERIC |
| unit | VARCHAR |
| created_at | TIMESTAMP |

### calculation_inputs

| Column | Type |
|---|---|
| calculation_id | UUID |
| financial_fact_id | UUID |

Composite PK:

```text
(calculation_id, financial_fact_id)
```

### research_sessions

| Column | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| created_at | TIMESTAMP |

### chat_messages

| Column | Type |
|---|---|
| id | UUID |
| session_id | UUID |
| role | ENUM |
| content | TEXT |
| created_at | TIMESTAMP |

### chat_citations

| Column | Type |
|---|---|
| message_id | UUID |
| evidence_id | UUID |

Composite PK:

```text
(message_id, evidence_id)
```

## 4. Indexes

Required:

- `documents(user_id, created_at)`
- `document_pages(document_id, page_number)`
- `financial_facts(document_id, metric_id, period_end)`
- `evidence(document_id, page_id)`
- vector index on `document_chunks.embedding`

## 5. Data Integrity

- monetary values use NUMERIC
- no floating-point financial storage
- document ownership enforced at API layer
- foreign keys enabled
- deletion policy documented
- migration required for schema changes
