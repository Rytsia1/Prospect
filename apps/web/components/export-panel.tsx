"use client";

import { useState } from "react";
import { ApiError, downloadFile } from "@/lib/api";
import { type ExportOptions, exportPath, type Financials, type Scope } from "@/lib/financials";

const FORMATS: [ExportOptions["format"], string][] = [
  ["csv", "CSV (financial facts with source page)"],
  ["json", "JSON (facts, calculations, reconciliation, evidence)"],
  ["xlsx", "XLSX (one sheet each: facts, calculations, reconciliation, evidence)"],
];
const RATIOS: [string, string][] = [
  ["revenue_growth", "Revenue growth"],
  ["net_margin", "Net margin"],
  ["roa", "ROA"],
  ["roe", "ROE"],
  ["debt_to_equity", "Debt-to-equity"],
  ["current_ratio", "Current ratio"],
  ["reconciliation", "Balance sheet reconciliation"],
];

function Checklist(props: {
  legend: string;
  options: [string, string][];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  const { legend, options, selected, onChange } = props;
  const all = selected.length === 0;
  return (
    <fieldset className="space-y-1">
      <legend className="font-medium">{legend}</legend>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={all} onChange={() => onChange([])} />
        All available
      </label>
      <div className="flex flex-wrap gap-x-4 gap-y-1">
        {options.map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={!all && selected.includes(value)}
              onChange={(e) =>
                onChange(
                  e.target.checked ? [...selected, value] : selected.filter((v) => v !== value),
                )
              }
            />
            {label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ExportPanel({
  fin,
  documentId,
  scope,
}: {
  fin: Financials;
  documentId: string;
  scope: Scope;
}) {
  const [format, setFormat] = useState<ExportOptions["format"]>("xlsx");
  const [periods, setPeriods] = useState<string[]>([]);
  const [metrics, setMetrics] = useState<string[]>([]);
  const [state, setState] = useState<"idle" | "working" | "done" | string>("idle");

  async function download() {
    setState("working");
    try {
      await downloadFile(exportPath(documentId, { format, scope, periods, metrics }));
      setState("done");
    } catch (e) {
      setState(e instanceof ApiError ? e.message : "The export failed.");
    }
  }

  const scopeText =
    scope === "company"
      ? `All ${fin.documents.length} reports of ${fin.company_name}`
      : "This document";

  return (
    <section aria-labelledby="export-heading" className="max-w-3xl space-y-4 text-sm">
      <div>
        <h2 id="export-heading" className="text-lg font-semibold">
          Export
        </h2>
        <p className="text-xs text-slate-500">
          Exports contain exactly the values shown in Prospect: monetary values in full currency
          units as exact decimals, calculations as plain ratios (0.181 = 18.1%), each row with its
          source page and a link to its evidence. Nothing is recalculated for the export.
        </p>
      </div>

      <p>
        <span className="font-medium">Scope:</span> {scopeText}
      </p>

      <fieldset className="space-y-1">
        <legend className="font-medium">Format</legend>
        {FORMATS.map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name="export-format"
              value={value}
              checked={format === value}
              onChange={() => setFormat(value)}
            />
            {label}
          </label>
        ))}
      </fieldset>

      <Checklist
        legend="Periods"
        options={fin.periods.map((p) => [p, p])}
        selected={periods}
        onChange={setPeriods}
      />
      <Checklist
        legend="Metrics"
        options={[...fin.metrics.map((m): [string, string] => [m.key, m.name]), ...RATIOS]}
        selected={metrics}
        onChange={setMetrics}
      />

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={download}
          disabled={state === "working"}
          className="rounded bg-slate-900 px-4 py-2 text-white hover:bg-slate-700 disabled:opacity-50"
        >
          {state === "working" ? "Preparing…" : `Download ${format.toUpperCase()}`}
        </button>
        <p role="status" className="text-slate-600">
          {state === "done" && "Downloaded."}
        </p>
        {!["idle", "working", "done"].includes(state) && (
          <p role="alert" className="text-red-800">
            {state}
          </p>
        )}
      </div>
    </section>
  );
}
