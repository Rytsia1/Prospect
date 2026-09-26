# Prospect Financial Calculation Specification

## 1. Purpose

Define deterministic financial calculations and their handling of incomplete or ambiguous inputs.

## 2. General Rules

1. Calculations operate on structured financial facts.
2. Monetary arithmetic uses decimal-safe types.
3. Inputs must have compatible periods.
4. Units/scales must be normalized before calculation.
5. Every result stores its formula and input fact IDs.
6. Division by zero returns an explicit unavailable state.
7. Missing inputs never become zero implicitly.

## 3. Unit Normalization

Examples:

```text
1 thousand = 1,000
1 million  = 1,000,000
1 billion  = 1,000,000,000
```

Normalized internal storage should use the actual numeric value rather than a display scale.

## 4. Revenue Growth

Formula:

```text
(current_revenue - previous_revenue) / previous_revenue
```

Requirements:

- periods must represent comparable reporting periods;
- previous revenue must be non-zero.

## 5. Net Income Growth

```text
(current_net_income - previous_net_income) / previous_net_income
```

If previous net income is zero, result is unavailable.

If previous net income is negative, the UI must avoid presenting the result as a conventional percentage-growth interpretation without context.

## 6. Net Margin

```text
net_income / revenue
```

Requires matching period.

## 7. ROA

Preferred formula:

```text
net_income / average_total_assets
```

where:

```text
average_total_assets =
(beginning_assets + ending_assets) / 2
```

If beginning assets are unavailable, Prospect may expose a clearly labeled ending-assets variant rather than silently substituting it.

## 8. ROE

Preferred:

```text
net_income / average_equity
```

Same beginning/ending principle as ROA.

## 9. Debt-to-Equity

```text
total_debt / equity
```

The definition of `total_debt` must be explicit in the metric mapping.

## 10. Current Ratio

```text
current_assets / current_liabilities
```

## 11. Rounding

Internal calculations retain full available precision.

Display rounding is separate from calculation precision.

Example:

```text
stored: 0.1814285714
display: 18.14%
```

## 12. Missing Data

Never:

```text
missing value → 0
```

Instead:

```text
status = UNAVAILABLE
reason = MISSING_INPUT
```

## 13. Negative Values

Preserve signed values exactly as extracted.

Do not normalize losses into positive values.

## 14. Period Compatibility

The calculation engine must validate:

- fiscal year
- period start/end
- annual vs quarterly
- consolidated vs standalone where available

## 15. Calculation Provenance

Every result must contain:

```text
calculation_id
formula_key
input_fact_ids
result
created_at
```

This enables:

```text
Result
 ↓
Why?
 ↓
Input Facts
 ↓
Evidence
 ↓
Source Page
```
