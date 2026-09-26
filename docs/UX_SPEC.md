# Prospect UX Specification

## 1. UX Principle

The interface should make the evidence chain visible without overwhelming the user.

## 2. Information Hierarchy

```text
FACT
  ↓
CALCULATION
  ↓
INTERPRETATION
```

Use consistent visual treatment for each category.

## 3. Dashboard

Purpose:

- see documents
- see processing states
- enter a document workspace

Components:

- upload button
- document list
- status badge
- fiscal year
- document type
- last updated

States:

- empty
- loading
- processing
- ready
- failed

## 4. Upload Flow

```text
Select PDF
 ↓
Validate
 ↓
Upload
 ↓
Queued
 ↓
Processing
 ↓
Ready
```

Show meaningful progress states rather than fake percentage progress.

## 5. Document Workspace

Recommended layout:

```text
┌────────────┬──────────────────────┬─────────────────┐
│ Sections   │ PDF Viewer           │ Research /      │
│            │                      │ Evidence        │
│ Income     │      Page 87         │                 │
│ Balance    │                      │ Revenue         │
│ Cash Flow  │                      │ Rp12.4T         │
│ Notes      │                      │ [Page 87]       │
└────────────┴──────────────────────┴─────────────────┘
```

## 6. Financial Overview

Display:

- key metrics
- trend
- change
- ratio cards
- source links

Example:

```text
Revenue
Rp 12.4T

+18.1% YoY

Source: Page 87
```

## 7. Evidence Interaction

Clicking `[Page 87]` should:

1. navigate PDF viewer to page 87;
2. preserve current context;
3. optionally highlight the relevant evidence region.

## 8. Research Chat

Answer format:

```text
Answer

FACTS
...

CALCULATIONS
...

EVIDENCE
[Page 87]
[Page 91]

INTERPRETATION
...
```

Only sections relevant to the question need to appear.

## 9. Empty States

Example:

```text
No documents yet.

Upload an annual report to start researching.
```

## 10. Failure State

Example:

```text
We couldn't confidently extract this table.

Page 112
Consolidated Cash Flow Statement

[Open Page]
```

Do not present low-confidence extraction as authoritative.

## 11. Accessibility

- keyboard navigation
- sufficient contrast
- semantic headings
- readable citation targets
- non-color-only distinctions
- loading/error states accessible to screen readers

## 12. Responsive Design

Desktop is the primary research experience.

Minimum responsive behavior:

- dashboard works on tablet
- document workspace collapses columns on smaller screens
- research panel remains usable
