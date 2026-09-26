# ADR-002: Evidence-First Financial Architecture

## Status

Accepted

## Context

LLMs can generate plausible but unsupported financial statements. Prospect must make source verification a core capability.

## Decision

Financial facts, evidence, and calculations are first-class domain objects.

The LLM cannot be the canonical source for:

- financial values
- formulas
- source pages
- calculation results

## Alternatives

### LLM-only extraction

Rejected for canonical financial data because provenance and deterministic validation are weaker.

### LLM plus hidden citations

Rejected because users need direct evidence navigation.

## Consequences

Prospect requires more data modeling and validation, but gains:

- traceability
- replaceable LLM providers
- deterministic calculations
- stronger evaluation
- more defensible research UX
