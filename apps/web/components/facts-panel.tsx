"use client";

import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  type FinancialFact,
  formatAmount,
  formatExact,
  METRIC_ORDER,
  printedLabel,
} from "@/lib/documents";

type Props = { documentId: string; onShowEvidence: (fact: FinancialFact) => void };

function byMetricThenPeriod(a: FinancialFact, b: FinancialFact): number {
  const metric = METRIC_ORDER.indexOf(a.metric) - METRIC_ORDER.indexOf(b.metric);
  return metric || b.period_label.localeCompare(a.period_label); // newest period first
}

export function pageText(fact: FinancialFact): string {
  const label = printedLabel({
    page_number: fact.evidence.page_number,
    label: fact.evidence.page_label,
  });
  return `Page ${fact.evidence.page_number}${label ? ` (p. ${label})` : ""}`;
}

export function FactsPanel({ documentId, onShowEvidence }: Props) {
  const [facts, setFacts] = useState<FinancialFact[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    // The API pages facts (at most 500 per request); follow next_offset to the end.
    async function load() {
      const all: FinancialFact[] = [];
      let offset: number | null = 0;
      while (offset !== null) {
        const page: { items: FinancialFact[]; next_offset: number | null } = await api(
          `/documents/${documentId}/metrics?limit=500&offset=${offset}`,
        );
        all.push(...page.items);
        offset = page.next_offset;
      }
      return all;
    }
    load()
      .then(setFacts)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load facts."));
  }, [documentId]);

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-800">
        {error}
      </p>
    );
  }
  if (!facts) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading financial facts…
      </p>
    );
  }

  const accepted = facts.filter((f) => f.status === "accepted").sort(byMetricThenPeriod);
  const review = facts.filter((f) => f.status === "needs_review").sort(byMetricThenPeriod);

  return (
    <section aria-labelledby="facts-heading" className="space-y-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="facts-heading" className="text-lg font-semibold">
          Financial facts
        </h2>
        <p className="text-xs text-slate-500">
          <FactBadge /> Values printed in this document, with the page they come from. Not
          calculated, not AI-generated.
        </p>
      </div>

      {accepted.length === 0 ? (
        <p className="rounded border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600">
          No financial facts were found with enough evidence. Prospect does not guess values,
          periods, units, or currencies.
        </p>
      ) : (
        <div className="overflow-x-auto rounded border border-slate-200">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
              <tr>
                <th className="px-3 py-2 font-semibold">Metric</th>
                <th className="px-3 py-2 font-semibold">Period</th>
                <th className="px-3 py-2 text-right font-semibold">Value</th>
                <th className="px-3 py-2 font-semibold">Evidence</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {accepted.map((f) => (
                <tr key={f.id}>
                  <td className="px-3 py-2">
                    <FactBadge /> <span className="ml-1">{f.metric_name}</span>
                  </td>
                  <td className="px-3 py-2 text-slate-600">
                    {f.period_type === "instant" ? `As at ${f.period_label}` : f.period_label}
                  </td>
                  <td
                    className="px-3 py-2 text-right font-medium"
                    title={formatExact(f.value, f.currency)}
                  >
                    {formatAmount(f.value, f.currency)}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => onShowEvidence(f)}
                      className="text-fact underline underline-offset-2"
                    >
                      {pageText(f)}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {review.length > 0 && (
        <details className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm">
          <summary className="cursor-pointer font-medium text-amber-900">
            {review.length} value{review.length === 1 ? "" : "s"} need review and are not shown as
            facts
          </summary>
          <ul className="mt-2 space-y-1">
            {review.map((f) => (
              <li key={f.id} className="flex flex-wrap gap-x-2">
                <span className="font-medium">{f.metric_name}</span>
                <span className="text-slate-600">{f.period_label}</span>
                <span className="font-mono text-xs text-slate-600">“{f.original_text}”</span>
                <span className="text-amber-900">{f.review_reasons.join("; ")}</span>
                <button type="button" onClick={() => onShowEvidence(f)} className="underline">
                  {pageText(f)}
                </button>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}

export function FactBadge() {
  return (
    <span className="rounded border border-fact px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-fact">
      Fact
    </span>
  );
}

/** Why Prospect believes a value: the exact source row and how it was read. */
export function EvidenceCard({ fact, onClose }: { fact: FinancialFact; onClose: () => void }) {
  const rows: [string, string | null][] = [
    ["Page", pageText(fact)],
    ["Section", fact.evidence.section_title ?? "Untitled section"],
    ["Column", fact.evidence.header],
    ["Unit", fact.evidence.unit],
    ["As printed", fact.original_text],
    ["Read as", formatExact(fact.value, fact.currency)],
  ];
  return (
    <aside
      aria-label="Evidence"
      className="rounded border-l-4 border-fact bg-slate-50 px-4 py-3 text-sm"
    >
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium">
          Evidence for {fact.metric_name}, {fact.period_label}
          {fact.status === "needs_review" && (
            <span className="ml-2 text-amber-900">(needs review, not a fact)</span>
          )}
        </p>
        <button type="button" onClick={onClose} className="text-slate-500 hover:text-slate-900">
          Close
        </button>
      </div>
      <p className="mt-2 break-words rounded bg-white px-2 py-1 font-mono text-xs">
        {fact.evidence.content}
      </p>
      <dl className="mt-2 grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1 text-xs">
        {rows
          .filter(([, v]) => v)
          .map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="text-slate-500">{k}</dt>
              <dd className="break-words">{v}</dd>
            </div>
          ))}
      </dl>
    </aside>
  );
}
