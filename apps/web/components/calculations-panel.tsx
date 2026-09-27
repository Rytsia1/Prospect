"use client";

import { useEffect, useState } from "react";
import { FactBadge, pageText } from "@/components/facts-panel";
import { ApiError, api } from "@/lib/api";
import {
  type Calculation,
  type FinancialFact,
  formatAmount,
  formatExact,
  formatRatio,
} from "@/lib/documents";

type Props = { documentId: string; onShowEvidence: (fact: FinancialFact) => void };

function inputText(fact: FinancialFact): string {
  const name = fact.metric_name.toLowerCase();
  return fact.period_type === "instant"
    ? `${name} at ${fact.period_label}`
    : `${fact.period_label} ${name}`;
}

export function CalculationsPanel({ documentId, onShowEvidence }: Props) {
  const [items, setItems] = useState<Calculation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ items: Calculation[] }>(`/documents/${documentId}/calculations`)
      .then((r) => setItems(r.items))
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load calculations."));
  }, [documentId]);

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-800">
        {error}
      </p>
    );
  }
  if (!items) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading calculations…
      </p>
    );
  }

  return (
    <section aria-labelledby="calculations-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="calculations-heading" className="text-lg font-semibold">
          Calculations
        </h2>
        <p className="text-xs text-slate-500">
          <CalculationBadge /> Computed by Prospect from the facts with a fixed formula. Not printed
          in the document, not AI-generated.
        </p>
      </div>

      {items.length === 0 ? (
        <p className="rounded border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600">
          No calculations: there are no financial facts to calculate from.
        </p>
      ) : (
        <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {items.map((c) => (
            <li key={c.id} className="rounded border border-slate-200 px-4 py-3 text-sm">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">{c.name}</p>
                  <p className="text-xs text-slate-500">
                    {c.period_type === "instant" ? `As at ${c.period_label}` : c.period_label}
                  </p>
                </div>
                <CalculationBadge />
              </div>

              {c.status === "calculated" && c.value !== null ? (
                <p className="mt-2 text-2xl font-semibold" title={`Exact ratio: ${c.value}`}>
                  {formatRatio(c.value, c.unit, c.metric === "revenue_growth")}
                </p>
              ) : (
                <p className="mt-2 text-slate-700">
                  <span className="font-semibold">Not possible.</span> {c.reason}
                </p>
              )}

              {c.inputs.length > 0 && (
                <p className="mt-1 text-xs text-slate-600">
                  {c.status === "calculated" ? "Based on" : "Found"}{" "}
                  {c.inputs.map(inputText).join(" and ")}.
                </p>
              )}
              {c.notes.map((n) => (
                <p key={n} className="mt-1 text-xs text-amber-900">
                  {n}
                </p>
              ))}

              <details className="mt-2">
                <summary className="cursor-pointer text-xs text-calc underline underline-offset-2">
                  View source inputs
                </summary>
                <p className="mt-2 font-mono text-xs text-slate-700">{c.formula}</p>
                <ul className="mt-2 space-y-1 text-xs">
                  {c.inputs.map((f) => (
                    <li key={f.id} className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      <FactBadge />
                      <span>
                        {f.metric_name}, {f.period_label}
                      </span>
                      <span className="font-medium" title={formatExact(f.value, f.currency)}>
                        {formatAmount(f.value, f.currency)}
                      </span>
                      <button
                        type="button"
                        onClick={() => onShowEvidence(f)}
                        className="text-fact underline underline-offset-2"
                      >
                        {pageText(f)}
                      </button>
                    </li>
                  ))}
                  {c.inputs.length === 0 && (
                    <li className="text-slate-500">No input facts were found.</li>
                  )}
                </ul>
              </details>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function CalculationBadge() {
  return (
    <span className="rounded border border-calc px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-calc">
      Calculation
    </span>
  );
}
