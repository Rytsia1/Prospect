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
| extraction_status | ENUM | success/partial/failed (partial = images but no text layer) |
| metadata | JSONB | label (printed page label), width/height (points), rotation, has_images, table_count |
| blocks | JSONB | ordered text/table blocks: index, kind, bbox [x0,y0,x1,y1] (points, top-left origin), text, font_size, bold, heading |

Unique:

```text
(document_id, page_number)
```

### document_sections

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK |
| ordinal | INTEGER | document order; unique per document |
| title | VARCHAR | nullable; verbatim heading text, NULL = generic section (no heading detected) |
| start_page | INTEGER | |
| end_page | INTEGER | |

### document_chunks

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK documents |
| page_id | UUID | composite FK (page_id, document_id, page_number) → document_pages |
| page_number | INTEGER | denormalized for retrieval; kept consistent by the composite FK |
| section_id | UUID | composite FK (section_id, document_id) → document_sections |
| chunk_index | INTEGER | order within the page |
| block_start / block_end | INTEGER | inclusive range into document_pages.blocks (source regions) |
| content | TEXT | verbatim text of those blocks |
| embedding | VECTOR | added with retrieval (Phase 5) |

Traceability: chunk → section → page → document, enforced by the database.

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
| metric_id | UUID | FK financial_metrics |
| evidence_id | UUID | required; composite FK (evidence_id, document_id) → evidence |
| value_numeric | NUMERIC | full value in currency units (scale applied), sign preserved |
| currency | CHAR(3) | nullable; required when status = accepted (never guessed) |
| scale | VARCHAR | units/thousands/millions/billions/trillions as printed in the source |
| original_text | VARCHAR | the value exactly as printed, e.g. "(1,250)" |
| original_unit | TEXT | the unit statement the scale came from, e.g. "(expressed in millions of Rupiah)" |
| period_type | ENUM | annual / quarter / interim / instant (balance-sheet date); never interchangeable |
| period_start | DATE | nullable |
| period_end | DATE | nullable: NULL when the document states only the year (not guessed) |
| period_label | VARCHAR | e.g. FY2025, Q4 2025, 2025-12-31 |
| fiscal_year | INTEGER | nullable |
| confidence | NUMERIC(5,4) | 0–1, deterministic score from how the value was found |
| extraction_method | VARCHAR | parser/llm/ocr/manual |
| status | ENUM | accepted (a FACT) / needs_review (kept for audit, never shown as a fact) |
| review_reasons | JSONB | why a value needs review, e.g. "currency not stated" |
| created_at | TIMESTAMP | required |

Unique: one accepted fact per (document, metric, period_type, period_label).

### evidence

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK |
| document_id | UUID | FK |
| page_id | UUID | composite FK (page_id, document_id, page_number) → document_pages |
| page_number | INTEGER | |
| section_id | UUID | composite FK (section_id, document_id) → document_sections |
| chunk_id | UUID | composite FK (chunk_id, page_id) → document_chunks |
| evidence_type | ENUM | table_row / text_line |
| content | TEXT | verbatim source row, a substring of the page text |
| bbox_json | JSONB nullable | [x0, y0, x1, y1] of the source block |
| locator | JSONB | block_index, row_index, column_index, header, unit |
| created_at | TIMESTAMP | |

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
