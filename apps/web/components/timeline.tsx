"use client";

import { useState } from "react";
import { CellValue, ChangeLine, SourceList } from "@/components/financial-values";
import { TrendChart } from "@/components/trend-chart";
import {
  CHART_METRICS,
  compareDecimal,
  type Financials,
  indexFinancials,
  type Scope,
} from "@/lib/financials";

type Sort = { by: string; descending: boolean }; // by: "metric" or a period

export function Timeline({
  fin,
  documentId,
  scope,
}: {
  fin: Financials;
  documentId: string;
  scope: Scope;
}) {
  const [sort, setSort] = useState<Sort>({ by: "metric", descending: false });
  const [chartMetric, setChartMetric] = useState("revenue");
  const index = indexFinancials(fin);
  const documents = new Map(fin.documents.map((d) => [d.id, d.filename]));
  const reportedValue = (metric: string, period: string) =>
    index.fact(index.cell(metric, period)?.primary_fact_id)?.value ?? null;
  const nameOf = (metric: string) => fin.metrics.find((m) => m.key === metric)?.name ?? metric;

  const rows = fin.metrics.filter((m) => fin.periods.some((p) => index.cell(m.key, p)));
  if (sort.by !== "metric") {
    // Rows without a value in the sort column go last, whichever the direction.
    rows.sort((a, b) => {
      const [x, y] = [reportedValue(a.key, sort.by), reportedValue(b.key, sort.by)];
      if (x === null || y === null) return x === y ? 0 : x === null ? 1 : -1;
      return compareDecimal(x, y) * (sort.descending ? -1 : 1);
    });
  } else if (sort.descending) {
    rows.reverse();
  }
  const conflicts = fin.cells.filter((c) => c.status === "conflict");

  function sortBy(by: string) {
    setSort((s) => ({ by, descending: s.by === by ? !s.descending : by !== "metric" }));
  }
  function sortState(by: string): "ascending" | "descending" | "none" {
    if (sort.by !== by) return "none";
    return sort.descending ? "descending" : "ascending";
  }
  function arrow(by: string) {
    return sort.by === by ? (sort.descending ? " ↓" : " ↑") : "";
  }

  if (!rows.length) {
    return <p className="text-sm text-slate-600">No annual or balance-sheet facts in scope.</p>;
  }

  return (
    <section aria-labelledby="timeline-heading" className="space-y-6">
      <div>
        <h2 id="timeline-heading" className="text-lg font-semibold">
          Financial timeline
        </h2>
        <p className="text-xs text-slate-500">
          Reported values (FACT) by period across {fin.documents.length} document
          {fin.documents.length === 1 ? "" : "s"}. A value repeated as a comparative in a later
          report is shown once; values that disagree are shown as conflicts, never overwritten.
        </p>
      </div>

      <div className="overflow-x-auto rounded border border-slate-200">
        <table className="w-full min-w-[40rem] text-sm">
          <caption className="sr-only">
            Financial metrics by period. Use the column buttons to sort.
          </caption>
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th scope="col" aria-sort={sortState("metric")} className="px-3 py-2">
                <button type="button" onClick={() => sortBy("metric")} className="uppercase">
                  Metric{arrow("metric")}
                </button>
              </th>
              {fin.periods.map((p) => (
                <th key={p} scope="col" aria-sort={sortState(p)} className="px-3 py-2 text-right">
                  <button type="button" onClick={() => sortBy(p)} className="uppercase">
                    {p}
                    {arrow(p)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200">
            {rows.map((m) => (
              <tr key={m.key}>
                <th scope="row" className="px-3 py-2 text-left font-medium">
                  {m.name}
                </th>
                {fin.periods.map((p) => {
                  const cell = index.cell(m.key, p);
                  return (
                    <td key={p} className="px-3 py-2 text-right align-top">
                      <CellValue cell={cell} index={index} />
                      {cell && (
                        <div className="flex justify-end">
                          <ChangeLine cell={cell} documentId={documentId} scope={scope} />
                        </div>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {conflicts.length > 0 && (
        <div className="space-y-3 rounded border border-amber-200 bg-amber-50 px-4 py-3 text-sm">
          <h3 className="font-semibold text-amber-900">⚠ Conflicting financial facts</h3>
          {conflicts.map((c) => (
            <div key={`${c.metric}|${c.period}`} className="space-y-1">
              <p className="font-medium">
                {nameOf(c.metric)} — {c.period}
              </p>
              <SourceList cell={c} index={index} documents={documents} />
            </div>
          ))}
          <p className="text-xs text-amber-900">
            Review the source documents. Calculations that need these values are not computed.
          </p>
        </div>
      )}

      <div className="space-y-2">
        <label className="flex items-center gap-2 text-sm">
          <span className="text-slate-600">Chart metric</span>
          <select
            value={chartMetric}
            onChange={(e) => setChartMetric(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {CHART_METRICS.map((key) => (
              <option key={key} value={key}>
                {nameOf(key)}
              </option>
            ))}
          </select>
        </label>
        <TrendChart
          title={nameOf(chartMetric)}
          points={fin.periods.map((p) => {
            const fact = index.fact(index.cell(chartMetric, p)?.primary_fact_id);
            return { period: p, value: fact?.value ?? null, currency: fact?.currency ?? null };
          })}
        />
      </div>
    </section>
  );
}
