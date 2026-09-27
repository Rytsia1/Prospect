"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CalculationBadge } from "@/components/calculations-panel";
import { FactBadge, pageText } from "@/components/facts-panel";
import { EvidenceLink, ResultValue } from "@/components/financial-values";
import { ApiError, api } from "@/lib/api";
import { formatExact } from "@/lib/documents";
import { type Financials, findCalculation, indexFinancials, type Scope } from "@/lib/financials";

/** A calculation and every source fact it used, each with its own page and evidence. */
export function CalculationExplorer(props: {
  documentId: string;
  calculationKey: string;
  period: string;
  scope: Scope;
}) {
  const { documentId, calculationKey, period, scope } = props;
  const [fin, setFin] = useState<Financials | null>(null);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();

  useEffect(() => {
    api<Financials>(`/documents/${documentId}/financials?scope=${scope}`)
      .then(setFin)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load."));
  }, [documentId, scope]);

  const back = (
    <div className="flex flex-wrap gap-4 text-sm">
      <button type="button" onClick={() => router.back()} className="text-slate-600 underline">
        ← Back
      </button>
      <Link href={`/documents/${documentId}`} className="text-slate-600 underline">
        Open document workspace
      </Link>
    </div>
  );

  if (error) {
    return (
      <div className="space-y-3">
        {back}
        <p role="alert" className="text-sm text-red-800">
          {error}
        </p>
      </div>
    );
  }
  if (!fin) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading calculation…
      </p>
    );
  }
  const result = findCalculation(fin, calculationKey, period);
  if (!result) {
    return (
      <div className="space-y-3">
        {back}
        <p className="text-sm text-slate-600">
          No such calculation for {period} in this {scope === "company" ? "company" : "document"}.
        </p>
      </div>
    );
  }
  const index = indexFinancials(fin);
  const documents = new Map(fin.documents.map((d) => [d.id, d.filename]));
  const inputs = result.input_fact_ids.map((i) => index.fact(i)).filter((f) => f !== undefined);
  const changeOf = fin.metrics.find((m) => `change:${m.key}` === calculationKey);
  const title = changeOf ? `${changeOf.name}, year-over-year change` : result.name;

  return (
    <div className="space-y-6">
      {back}
      <div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        <p className="flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <CalculationBadge /> {result.period} ·{" "}
          <span className="text-lg font-semibold text-slate-900">
            <ResultValue
              result={result}
              signed={Boolean(changeOf) || result.metric === "revenue_growth"}
            />
          </span>
        </p>
        <p className="text-sm text-slate-600">
          Computed by Prospect from {inputs.length} source fact{inputs.length === 1 ? "" : "s"}
          {inputs.length > 1 ? ", each on the page shown below" : ""}; not printed in the document.
        </p>
      </div>

      <dl className="grid max-w-3xl grid-cols-[8rem_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-slate-500">Formula</dt>
        <dd className="font-mono text-xs">{result.formula}</dd>
        {result.value !== null && (
          <>
            <dt className="text-slate-500">Exact result</dt>
            <dd className="break-all font-mono text-xs">{result.value}</dd>
          </>
        )}
        {result.reason && (
          <>
            <dt className="text-slate-500">Not possible</dt>
            <dd>{result.reason}</dd>
          </>
        )}
        {result.notes.map((n) => (
          <div key={n} className="contents">
            <dt className="text-slate-500">Note</dt>
            <dd className="text-amber-900">{n}</dd>
          </div>
        ))}
      </dl>

      <section aria-labelledby="inputs-heading" className="space-y-2">
        <h2 id="inputs-heading" className="text-lg font-semibold">
          Source inputs
        </h2>
        {inputs.length === 0 ? (
          <p className="text-sm text-slate-600">No input facts were found.</p>
        ) : (
          <ul className="grid gap-3 md:grid-cols-2">
            {inputs.map((f) => (
              <li
                key={f.id}
                className="space-y-1 rounded border border-slate-200 px-3 py-3 text-sm"
              >
                <p className="flex flex-wrap items-center gap-2 font-medium">
                  <FactBadge /> {f.metric_name}, {f.period_label}
                </p>
                <p className="text-lg font-semibold">{formatExact(f.value, f.currency)}</p>
                <p className="text-xs text-slate-600">
                  {documents.get(f.document_id)} · {pageText(f)} ·{" "}
                  {f.evidence.section_title ?? "Untitled section"}
                </p>
                <p className="break-words rounded bg-slate-50 px-2 py-1 font-mono text-xs">
                  {f.evidence.content}
                </p>
                <EvidenceLink fact={f} label="Open in evidence explorer" />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
