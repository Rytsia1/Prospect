"use client";

import Link from "next/link";
import { createContext, useContext } from "react";
import { CalculationBadge } from "@/components/calculations-panel";
import { FactBadge, pageText } from "@/components/facts-panel";
import {
  changeArrow,
  type FinancialFact,
  formatAmount,
  formatExact,
  formatRatio,
} from "@/lib/documents";
import {
  type Cell,
  calculationPath,
  evidencePath,
  type indexFinancials,
  type Result,
  type Scope,
} from "@/lib/financials";

type Index = ReturnType<typeof indexFinancials>;

/** Inside a document workspace: open a fact's source in the side panel (SourcePanel) instead of
 * navigating away. Elsewhere (no provider) evidence links go to the evidence explorer page. */
export const ShowEvidence = createContext<((fact: FinancialFact) => void) | null>(null);

export function EvidenceLink({ fact, label }: { fact: FinancialFact; label?: string }) {
  const show = useContext(ShowEvidence);
  return (
    <Link
      href={evidencePath(fact)}
      onClick={(e) => {
        // A plain click opens the panel; ctrl/cmd/shift/middle click still opens the page.
        if (!show || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
        e.preventDefault();
        show(fact);
      }}
      className="text-fact underline underline-offset-2"
    >
      {label ?? pageText(fact)}
    </Link>
  );
}

/** A calculated value, or "Not possible". Never presented as a reported figure. */
export function ResultValue({ result, signed = false }: { result: Result; signed?: boolean }) {
  if (result.status === "calculated" && result.value !== null) {
    const text = formatRatio(result.value, result.unit, signed);
    const arrow = signed && changeArrow(text);
    return (
      <span title={`Exact ratio: ${result.value}`}>
        {arrow && <span aria-hidden="true">{arrow} </span>}
        {text}
      </span>
    );
  }
  return (
    <span className="text-slate-600" title={result.reason ?? undefined}>
      Not possible
    </span>
  );
}

/** Year-over-year change under a reported value, labeled as a calculation. */
export function ChangeLine({
  cell,
  documentId,
  scope,
}: {
  cell: Cell;
  documentId: string;
  scope: Scope;
}) {
  if (!cell.change) return null;
  return (
    <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-slate-600">
      <span>YoY</span>
      <span className="font-medium text-slate-800">
        <ResultValue result={cell.change} signed />
      </span>
      <CalculationBadge />
      <Link
        href={calculationPath(documentId, scope, `change:${cell.metric}`, cell.period)}
        className="text-calc underline underline-offset-2"
      >
        inputs
      </Link>
    </p>
  );
}

/** A reported value (FACT), a conflict, a value under review, or an explicit gap. */
export function CellValue({ cell, index }: { cell: Cell | undefined; index: Index }) {
  if (!cell) return <span className="text-slate-400">Not found</span>;
  const facts = cell.fact_ids.map((id) => index.fact(id)).filter((f) => f !== undefined);
  if (cell.status === "value") {
    const fact = index.fact(cell.primary_fact_id);
    if (!fact) return null;
    const page = fact.evidence.page_label ?? String(fact.evidence.page_number);
    return (
      <span className="inline-flex flex-wrap items-baseline justify-end gap-x-2">
        <span title={formatExact(fact.value, fact.currency)}>
          {formatAmount(fact.value, fact.currency)}
        </span>
        <span className="text-xs font-normal">
          <EvidenceLink fact={fact} label={`p. ${page}`} />
        </span>
        {facts.length > 1 && (
          <span className="text-xs font-normal text-slate-500">({facts.length} sources agree)</span>
        )}
      </span>
    );
  }
  if (cell.status === "conflict") {
    return (
      <span className="text-amber-900">
        ⚠ Conflict: {facts.map((f) => formatAmount(f.value, f.currency)).join(" vs ")}
      </span>
    );
  }
  return <span className="text-amber-900">⚠ Needs review</span>;
}

/** The sources behind a conflict or review item, each with its evidence. */
export function SourceList({
  cell,
  index,
  documents,
}: {
  cell: Cell;
  index: Index;
  documents: Map<string, string>;
}) {
  return (
    <ul className="space-y-1">
      {cell.fact_ids.map((id) => {
        const f = index.fact(id);
        if (!f) return null;
        return (
          <li key={id} className="flex flex-wrap items-baseline gap-x-2">
            <FactBadge />
            <span>{documents.get(f.document_id) ?? "Document"}:</span>
            <span className="font-medium" title={formatExact(f.value, f.currency)}>
              {formatAmount(f.value, f.currency)}
            </span>
            {f.status === "needs_review" && (
              <span className="text-amber-900">({f.review_reasons.join("; ")})</span>
            )}
            <EvidenceLink fact={f} />
          </li>
        );
      })}
    </ul>
  );
}
