# Prospect MVP Specification

## 1. Purpose

Define the exact behavior and acceptance criteria for the first usable Prospect release.

## 2. MVP Principle

The MVP is a single evidence-first vertical slice expanded into a small research workspace.

```text
Upload PDF
  ↓
Process
  ↓
Extract financial facts
  ↓
Attach evidence
  ↓
Calculate metrics
  ↓
Research / inspect evidence
```

## 3. Supported Inputs

Initial supported document:

- PDF
- Annual Report
- Financial Statement
- Prospectus

Initial MVP test corpus should contain manually verified public financial documents.

## 4. MVP Features

### 4.1 Authentication

MVP may begin with single-user development mode, but the architecture must keep document ownership explicit.

Acceptance:

- [ ] user identity exists in the domain model
- [ ] documents have an owner
- [ ] API does not expose another user's document

### 4.2 Upload

Acceptance:

- [ ] accepts PDF
- [ ] rejects unsupported MIME types
- [ ] enforces configurable file-size limit
- [ ] creates document ID
- [ ] stores original file privately
- [ ] creates `UPLOADED`/`QUEUED` processing state

### 4.3 Processing

Acceptance:

- [ ] processing runs asynchronously
- [ ] status is persisted
- [ ] pages are extracted
- [ ] text is extracted
- [ ] tables are attempted
- [ ] sections are detected where possible
- [ ] failures are persisted
- [ ] retry is possible for retryable failures

### 4.4 Financial Extraction

Initial metrics:

- Revenue
- Gross Profit
- Operating Income
- Net Income
- Cash
- Total Assets
- Total Liabilities
- Equity
- Total Debt

Every extracted value must include:

```text
metric
value
currency
scale
period
document_id
page
section
confidence
evidence_id
```

### 4.5 Calculations

Initial calculations:

- Revenue Growth
- Net Income Growth
- Net Margin
- ROA
- ROE
- Debt-to-Equity
- Current Ratio

Calculations must be performed by deterministic application code.

### 4.6 Evidence Viewer

Acceptance:

- [ ] evidence displays source document
- [ ] evidence identifies page
- [ ] clicking citation opens the relevant page
- [ ] extracted text can be inspected
- [ ] unavailable evidence is explicitly marked

### 4.7 Research Query

The user can ask questions about processed documents.

Minimum supported behavior:

- retrieve relevant evidence
- use structured facts where appropriate
- generate an answer
- cite supporting pages
- state insufficient evidence when necessary

## 5. MVP Vertical Slice

Input:

`Annual_Report_2025.pdf`

Expected pipeline:

```text
PDF
 ↓
Page 87
 ↓
Income Statement
 ↓
Revenue FY2025
Revenue FY2024
 ↓
Structured facts
 ↓
Evidence references
 ↓
Revenue Growth
 ↓
UI
```

UI result:

```text
Revenue
FY2025: Rp X

Revenue Growth
+Y%

Source
Annual Report 2025 — Page 87
```

## 6. Explicit MVP Exclusions

Do not implement initially:

- stock-price prediction
- investment recommendations
- automated valuation
- portfolio optimization
- sentiment scoring
- custom model training
- broad accounting-standard support
- arbitrary document formats
- multi-tenant organization billing

## 7. Acceptance Gate

MVP is accepted only when the vertical slice passes using at least three independently verified annual reports.
