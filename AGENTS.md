# Prospect Agent Engineering Rules

## Project Mission

Build Prospect as an evidence-first financial document intelligence platform.

## Non-Negotiable Rules

1. Never use floating-point types for stored financial values.
2. Use decimal-safe arithmetic for financial calculations.
3. Every extracted financial fact must have provenance.
4. Never fabricate evidence, citations, pages, values, or quotations.
5. If evidence is insufficient, represent uncertainty explicitly.
6. Financial calculations belong in deterministic application code, not LLM prompts.
7. The LLM is an interpretation/retrieval layer, not the financial source of truth.
8. Database changes require migrations.
9. API contracts must use typed request/response schemas.
10. Business logic must be unit tested.
11. New financial formulas require formula tests and edge-case tests.
12. Do not add dependencies without documenting why they are needed.
13. Keep provider-specific AI integrations behind an abstraction.
14. Do not expose private object-storage URLs publicly.
15. Do not put secrets in source code, tests, fixtures, or documentation.
16. Preserve document ownership boundaries in every document query.
17. Prefer small, testable modules over large service classes.
18. Do not silently replace missing values with zero.
19. Do not silently substitute incompatible accounting periods.
20. Do not change architecture merely to make a single feature easier.

## Coding Style

- prefer explicit names over clever abstractions;
- keep functions focused;
- validate external input at boundaries;
- use structured logging;
- return typed errors;
- write tests beside meaningful domain behavior.

## AI Code Generation

Before implementing a feature:

1. inspect the relevant specification;
2. inspect existing architecture;
3. identify affected modules;
4. make the smallest coherent change;
5. run relevant tests;
6. report assumptions and unresolved issues.

Never rewrite unrelated modules simply because they could be "cleaner."

## Financial Domain Rules

Financial values must preserve:

- sign
- currency
- scale
- period
- consolidation context where available

A value without sufficient provenance must not be treated as authoritative.

## Evidence Rules

Every evidence object should be traceable to:

```text
document
→ page
→ section/chunk
→ source content
```

## Pull Request / Change Summary

Every substantial change should explain:

- what changed;
- why;
- affected components;
- tests run;
- known limitations.
