# Prospect Evaluation & Test Plan

## 1. Objective

Measure whether Prospect extracts, calculates, retrieves, and cites financial information correctly.

## 2. Evaluation Corpus

Create a manually verified benchmark containing at least:

- 3 annual reports for MVP
- 10+ documents for a stronger portfolio evaluation

For each document record:

- company
- fiscal year
- document type
- language
- page count
- relevant financial statement pages

## 3. Ground Truth

For selected metrics, manually verify:

```text
metric
value
currency
scale
period
page
section
```

## 4. Extraction Metrics

### Numerical Accuracy

```text
correct values / evaluated values
```

### Period Accuracy

```text
correct periods / evaluated periods
```

### Citation Accuracy

```text
correct source pages / cited source pages
```

### Currency Accuracy

```text
correct currencies / evaluated currencies
```

## 5. Calculation Tests

For each formula test:

- normal positive case
- zero denominator
- negative input
- missing input
- mismatched period
- scale normalization

## 6. RAG Evaluation

Measure:

### Retrieval Recall

Whether relevant evidence appears in retrieved context.

### Citation Precision

Whether citations actually support the answer.

### Unsupported Claim Rate

Percentage of material claims not supported by retrieved evidence.

### Answer Completeness

Whether the answer addresses the question using available evidence.

## 7. Golden Questions

Example categories:

```text
Numeric:
"What was revenue in FY2025?"

Comparison:
"How did revenue change from 2024 to 2025?"

Calculation:
"What was the revenue growth?"

Explanation:
"What reasons did management give for revenue growth?"

Mixed:
"Revenue increased. Did profitability also improve?"
```

Each question should have expected:

- answer facts
- expected evidence pages
- expected calculations
- acceptable interpretation boundaries

## 8. Regression Testing

Every bug discovered from the evaluation corpus should become a regression test where practical.

## 9. Release Gate

A candidate MVP should not ship if:

- calculations fail deterministic unit tests;
- financial facts lack provenance;
- citations frequently point to irrelevant pages;
- the system fabricates evidence;
- document access control is broken.

No arbitrary accuracy threshold should be treated as universal; thresholds should be established from the benchmark and product risk.
