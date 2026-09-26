# ADR-003: Asynchronous Document Processing

## Status

Accepted

## Context

Large PDFs may take substantial time to parse, OCR, extract tables, and embed.

## Decision

Document processing runs asynchronously through a worker/job system.

## Alternatives

### Synchronous HTTP processing

Rejected because request duration becomes unpredictable and fragile.

### Serverless-only processing

Deferred because long-running document jobs may exceed execution limits and complicate local development.

## Consequences

Positive:

- resilient processing
- progress states
- retry support
- scalable workers

Negative:

- queue infrastructure
- more complex local development
- eventual consistency in document readiness
