// Types and pure helpers for the research workspace (GET /documents/{id}/financials).
// The UI never calculates financial values: every value, change and ratio comes from the API.
// Helpers here only look values up, compare them for sorting, and place them on a chart.

import type { FinancialFact } from "./documents.ts";

export type Scope = "document" | "company";

// Document workspace tabs. Here (not in the client component) so the server route can read them.
export const TABS = [
  ["overview", "Overview"],
  ["financials", "Financials"],
  ["timeline", "Timeline"],
  ["evidence", "Evidence"],
  ["reconciliation", "Reconciliation"],
  ["export", "Export"],
] as const;
export type Tab = (typeof TABS)[number][0];

export type Result = {
  metric: string;
  name: string;
  formula_key: string;
  formula: string;
  period: string;
  period_type: FinancialFact["period_type"];
  period_label: string;
  status: "calculated" | "not_possible";
  value: string | null; // plain ratio, full precision
  unit: "percent" | "times";
  reason_code: string | null;
  reason: string | null;
  notes: string[];
  input_fact_ids: string[];
};

export type Cell = {
  metric: string;
  period: string;
  status: "value" | "conflict" | "needs_review";
  fact_ids: string[];
  primary_fact_id: string | null;
  change: Result | null;
};

export type ReconciliationStatus =
  | "BALANCED"
  | "ROUNDING_DIFFERENCE"
  | "MISMATCH"
  | "INSUFFICIENT_DATA";

export type Reconciliation = {
  check: "balance_sheet";
  formula: string;
  period: string;
  status: ReconciliationStatus;
  fact_ids: Partial<Record<"total_assets" | "total_liabilities" | "equity", string>>;
  liabilities_plus_equity: string | null;
  difference: string | null;
  tolerance: string | null;
  currency: string | null;
  problems: string[];
};

export type QualityItem = {
  period: string;
  level: "ok" | "warning" | "info";
  message: string;
  metric: string | null;
};

export type Financials = {
  scope: Scope;
  company_name: string | null;
  documents: {
    id: string;
    filename: string;
    fiscal_year: number | null;
    company_name: string | null;
  }[];
  metrics: { key: string; name: string }[];
  periods: string[];
  period_basis: Record<string, "fiscal_year" | "fiscal_year_end" | "date">;
  facts: FinancialFact[];
  fact_periods: Record<string, string>;
  cells: Cell[];
  calculations: Result[];
  reconciliations: Reconciliation[];
  quality: QualityItem[];
};

// Text and symbol always accompany color (never color alone).
export const RECONCILIATION_TEXT: Record<ReconciliationStatus, { symbol: string; label: string }> =
  {
    BALANCED: { symbol: "✓", label: "Balanced" },
    ROUNDING_DIFFERENCE: { symbol: "≈", label: "Rounding difference" },
    MISMATCH: { symbol: "✕", label: "Mismatch" },
    INSUFFICIENT_DATA: { symbol: "–", label: "Insufficient data" },
  };
export const QUALITY_SYMBOL: Record<QualityItem["level"], string> = {
  ok: "✓",
  warning: "⚠",
  info: "–",
};

export const CHART_METRICS = [
  "revenue",
  "net_income",
  "total_assets",
  "total_liabilities",
  "equity",
  "cash",
  "total_debt",
];

export function indexFinancials(fin: Financials) {
  const facts = new Map(fin.facts.map((f) => [f.id, f]));
  const cells = new Map(fin.cells.map((c) => [`${c.metric}|${c.period}`, c]));
  return {
    fact: (id: string | null | undefined) => (id ? facts.get(id) : undefined),
    cell: (metric: string, period: string) => cells.get(`${metric}|${period}`),
    calculation: (metric: string, period: string) =>
      fin.calculations.find((r) => r.metric === metric && r.period === period),
  };
}

/** The most recent period that has any reported value. */
export function latestPeriod(fin: Financials): string | null {
  const withValues = new Set(fin.cells.filter((c) => c.status === "value").map((c) => c.period));
  return [...fin.periods].reverse().find((p) => withValues.has(p)) ?? fin.periods.at(-1) ?? null;
}

/** Integer representation of a decimal string, scaled by 10^digits (exact, no floats). */
export function toScaled(value: string, digits = 4): bigint {
  const negative = value.startsWith("-");
  const [int, fraction = ""] = value.replace(/^[-+]/, "").split(".");
  const scaled = BigInt(int + fraction.padEnd(digits, "0").slice(0, digits));
  return negative ? -scaled : scaled;
}

/** Order two decimal strings exactly. */
export function compareDecimal(a: string, b: string): number {
  const digits = Math.max(a.split(".")[1]?.length ?? 0, b.split(".")[1]?.length ?? 0);
  const [x, y] = [toScaled(a, digits), toScaled(b, digits)];
  return x < y ? -1 : x > y ? 1 : 0;
}

/**
 * Chart geometry for a series of decimal strings (null = no value for that period).
 * Positions are computed with integer math; only the final pixel coordinate is a Number.
 */
export function chartPoints(
  values: (string | null)[],
  width: number,
  height: number,
  pad = 8,
): ({ x: number; y: number } | null)[] {
  const scaled = values.map((v) => (v === null ? null : toScaled(v)));
  const present = scaled.filter((v): v is bigint => v !== null);
  if (!present.length) return values.map(() => null);
  const min = present.reduce((a, b) => (b < a ? b : a));
  const max = present.reduce((a, b) => (b > a ? b : a));
  const span = max - min;
  const usable = BigInt(Math.max(height - 2 * pad, 1));
  const step = values.length > 1 ? (width - 2 * pad) / (values.length - 1) : 0;
  return scaled.map((v, i) => {
    if (v === null) return null;
    const offset = span === 0n ? usable / 2n : ((max - v) * usable) / span;
    const x = values.length > 1 ? pad + i * step : width / 2;
    return { x, y: pad + Number(offset) };
  });
}

export type ExportOptions = {
  format: "csv" | "json" | "xlsx";
  scope: Scope;
  periods: string[]; // empty: all
  metrics: string[]; // empty: all
};

export function exportPath(documentId: string, o: ExportOptions): string {
  const params = new URLSearchParams({ format: o.format, scope: o.scope });
  for (const p of o.periods) params.append("periods", p);
  for (const m of o.metrics) params.append("metrics", m);
  return `/documents/${documentId}/export?${params}`;
}

/** Calculation explorer route: ratios keyed by metric, year-over-year changes by `change:metric`. */
export function calculationPath(documentId: string, scope: Scope, key: string, period: string) {
  const params = new URLSearchParams({ period, scope });
  return `/documents/${documentId}/calculations/${encodeURIComponent(key)}?${params}`;
}

/** Find the calculation a calculation-explorer key names. */
export function findCalculation(fin: Financials, key: string, period: string): Result | undefined {
  if (key.startsWith("change:")) {
    const metric = key.slice("change:".length);
    return fin.cells.find((c) => c.metric === metric && c.period === period)?.change ?? undefined;
  }
  return indexFinancials(fin).calculation(key, period);
}

export function evidencePath(fact: FinancialFact): string {
  return `/documents/${fact.document_id}/evidence/${fact.evidence.id}`;
}
