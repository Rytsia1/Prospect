# ADR-004: Decimal Financial Arithmetic

## Status

Accepted

## Context

Financial calculations require predictable decimal behavior.

## Decision

Use:

- Python Decimal in application calculations
- PostgreSQL NUMERIC/DECIMAL for stored values

## Alternatives

### float

Rejected for canonical financial calculations.

## Consequences

Calculations are more predictable but require deliberate serialization and formatting at API/UI boundaries.
