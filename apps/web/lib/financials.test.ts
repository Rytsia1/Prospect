import assert from "node:assert/strict";
import { test } from "node:test";
import type { FinancialFact } from "./documents.ts";
import {
  type Cell,
  chartPoints,
  compareDecimal,
  evidenceKey,
  exportPath,
  type Financials,
  findCalculation,
  indexFinancials,
  latestPeriod,
  latestValueCell,
  parseEvidenceKey,
  type Result,
} from "./financials.ts";

const change: Result = {
  metric: "yoy_change",
  name: "Year-over-year change",
  formula_key: "yoy_change",
  formula: "…",
  period: "FY2025",
  period_type: "annual",
  period_label: "FY2025",
  status: "calculated",
  value: "0.18",
  unit: "percent",
  reason_code: null,
  reason: null,
  notes: [],
  input_fact_ids: ["a", "b"],
};
const cell = (metric: string, period: string, status: Cell["status"], id: string | null): Cell => ({
  metric,
  period,
  status,
  fact_ids: id ? [id] : [],
  primary_fact_id: status === "value" ? id : null,
  change: metric === "revenue" && period === "FY2025" ? change : null,
});
const fin = {
  periods: ["FY2023", "FY2024", "FY2025", "FY2026"],
  facts: [{ id: "b", value: "12400000000000" } as FinancialFact],
  cells: [
    cell("revenue", "FY2024", "conflict", null),
    cell("revenue", "FY2025", "value", "b"),
    cell("revenue", "FY2026", "needs_review", "c"),
  ],
  calculations: [{ ...change, metric: "roe", formula_key: "roe_average_equity" }],
} as unknown as Financials;

test("latest period is the newest one with a reported value, not one under review", () => {
  assert.equal(latestPeriod(fin), "FY2025");
});

test("a company's latest figure skips newer periods in conflict or under review", () => {
  assert.equal(latestValueCell(fin, "revenue")?.period, "FY2025");
  assert.equal(latestValueCell(fin, "net_income"), undefined);
});

test("period switching looks values up by metric and period", () => {
  const index = indexFinancials(fin);
  assert.equal(
    index.fact(index.cell("revenue", "FY2025")?.primary_fact_id)?.value,
    "12400000000000",
  );
  assert.equal(index.cell("revenue", "FY2024")?.status, "conflict");
  assert.equal(index.cell("net_income", "FY2025"), undefined);
});

test("calculation explorer keys resolve ratios and year-over-year changes", () => {
  assert.equal(findCalculation(fin, "roe", "FY2025")?.formula_key, "roe_average_equity");
  assert.equal(findCalculation(fin, "change:revenue", "FY2025")?.formula_key, "yoy_change");
  assert.equal(findCalculation(fin, "change:revenue", "FY2024"), undefined);
});

test("decimal comparison is exact beyond float precision", () => {
  assert.equal(compareDecimal("9007199254740993", "9007199254740992"), 1);
  assert.equal(compareDecimal("-1.5", "-1.25"), -1);
  assert.equal(compareDecimal("2.50", "2.5"), 0);
});

test("chart geometry: highest value at the top, gaps stay gaps", () => {
  const points = chartPoints(["100", null, "300", "200"], 316, 116);
  assert.deepEqual(points[0], { x: 8, y: 108 });
  assert.equal(points[1], null);
  assert.deepEqual(points[2], { x: 208, y: 8 });
  assert.deepEqual(points[3], { x: 308, y: 58 });
  assert.deepEqual(chartPoints(["5"], 100, 100), [{ x: 50, y: 50 }]);
  assert.deepEqual(chartPoints([null], 100, 100), [null]);
});

test("export path carries format, scope and selections", () => {
  const path = exportPath("d1", {
    format: "xlsx",
    scope: "company",
    periods: ["FY2024", "FY2025"],
    metrics: ["revenue"],
  });
  assert.equal(
    path,
    "/documents/d1/export?format=xlsx&scope=company&periods=FY2024&periods=FY2025&metrics=revenue",
  );
});

test("an evidence key round-trips and nothing else parses as one", () => {
  const documentId = "0b7e8a2e-6f1d-4c1a-9a55-2f1c3d4e5f60";
  const evidenceId = "9c1d2e3f-4a5b-4c6d-8e7f-001122334455";
  const fact = { document_id: documentId, evidence: { id: evidenceId } } as FinancialFact;
  assert.deepEqual(parseEvidenceKey(evidenceKey(fact)), { documentId, evidenceId });
  for (const bad of [
    null,
    "",
    documentId,
    `${documentId}:x`,
    `../x:${evidenceId}`,
    `${documentId}:${evidenceId}:x`,
  ]) {
    assert.equal(parseEvidenceKey(bad), null, String(bad));
  }
});
