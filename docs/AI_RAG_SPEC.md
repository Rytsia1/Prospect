# Prospect AI / RAG Specification

## 1. Objective

Provide useful natural-language research while keeping material claims grounded in document evidence and structured financial facts.

## 2. Core Rule

> The LLM explains evidence; it does not become the source of truth.

## 3. Retrieval Strategy

Use multiple retrieval paths.

```text
Question
 ├── Query classification
 │
 ├── Structured retrieval
 │     └── financial_facts / calculations
 │
 ├── lexical retrieval
 │     └── document text
 │
 └── semantic retrieval
       └── pgvector chunks
                ↓
         Evidence fusion
                ↓
         Context builder
                ↓
              LLM
                ↓
        Citation validation
                ↓
             Answer
```

## 4. Query Classes

### Numeric Fact

Example:

> What was revenue in 2025?

Preferred source:

```text
financial_facts
```

Do not use an LLM to calculate or infer the number if a structured fact exists.

### Calculation

Example:

> How much did revenue grow?

Preferred:

```text
financial_facts
→ calculation engine
```

### Document Explanation

Example:

> What reasons did management give for the increase?

Preferred:

```text
semantic / lexical retrieval
→ evidence
→ LLM synthesis
```

### Mixed Analysis

Example:

> Revenue increased, but did profitability improve?

Use:

```text
financial_facts
+
calculation engine
+
document evidence
+
LLM explanation
```

## 5. Context Construction

Retrieved context should preserve:

- document ID
- page number
- section
- evidence ID
- source text
- metric identity when applicable

The model must receive citation identifiers that can be mapped back to database evidence.

## 6. Answer Rules

The model should:

- answer only from supplied evidence;
- cite material claims;
- distinguish reported facts from interpretation;
- avoid invented page numbers;
- avoid fabricated quotations;
- explicitly state when evidence is insufficient.

## 7. Citation Validation

After generation:

1. parse cited evidence IDs;
2. verify they exist;
3. verify they belong to the user's accessible documents;
4. ensure cited evidence was actually retrieved;
5. remove or flag invalid citations.

## 8. Prompt Boundary

System prompt should define:

- role
- evidence constraints
- citation format
- uncertainty behavior
- distinction between fact/calculation/interpretation

Business logic must remain outside the prompt.

## 9. LLM Provider Abstraction

Implement an internal interface such as:

```text
LLMProvider
 ├── generate()
 └── embed()
```

The application should not depend directly on a single vendor throughout the codebase.

## 10. Hallucination Controls

- structured fact lookup before generation
- evidence-only context
- citation validation
- low-temperature generation where appropriate
- explicit insufficient-evidence response
- evaluation benchmark
