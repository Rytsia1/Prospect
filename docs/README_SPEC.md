# Prospect Pre-Coding Specification

This directory contains the design artifacts required before implementation.

## Recommended Order

1. `PRD.md`
2. `MVP_SPEC.md`
3. `ARCHITECTURE.md`
4. `DATA_MODEL.md`
5. `API_SPEC.yaml`
6. `FINANCIAL_CALCULATIONS.md`
7. `AI_RAG_SPEC.md`
8. `UX_SPEC.md`
9. `EVALUATION.md`
10. `AGENTS.md`
11. ADRs

## First Coding Milestone

Do not start with the complete chatbot.

Implement:

```text
Upload Annual Report
      ↓
Process PDF
      ↓
Extract Revenue
      ↓
Attach Page Evidence
      ↓
Extract Previous-Year Revenue
      ↓
Calculate Revenue Growth
      ↓
Display Fact + Calculation + Source
```

This is the first vertical slice and the architectural proof that Prospect's core idea works.
