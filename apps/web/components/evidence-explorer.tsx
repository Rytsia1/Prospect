"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FactBadge, pageText } from "@/components/facts-panel";
import { PageViewer } from "@/components/page-viewer";
import { ApiError, api } from "@/lib/api";
import { type FinancialFact, formatExact } from "@/lib/documents";

type View = {
  document: { id: string; filename: string; fiscal_year: number | null };
  fact: FinancialFact;
};

const PERIOD_TYPE = {
  annual: "Annual",
  quarter: "Quarter",
  interim: "Interim",
  instant: "Balance-sheet date",
};

/** Where one financial fact came from: document, page, section, source text, and how it was read. */
export function EvidenceExplorer({
  documentId,
  evidenceId,
}: {
  documentId: string;
  evidenceId: string;
}) {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [page, setPage] = useState<number | null>(null);
  const router = useRouter();

  useEffect(() => {
    api<View>(`/documents/${documentId}/evidence/${evidenceId}`)
      .then((v) => {
        setView(v);
        setPage(v.fact.evidence.page_number);
      })
      .catch((e) =>
        setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Could not load.")),
      );
  }, [documentId, evidenceId]);

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
        <h1 className="text-xl font-semibold">Evidence explorer</h1>
        <p role="alert" className="text-sm text-red-800">
          {error.status === 404 ? "This evidence does not exist." : error.message}
        </p>
      </div>
    );
  }
  if (!view || page === null) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading evidence…
      </p>
    );
  }

  const { fact, document } = view;
  const rows: [string, string | null][] = [
    ["Document", document.filename],
    ["Page", pageText(fact)],
    ["Section", fact.evidence.section_title ?? "Untitled section"],
    ["Metric", fact.metric_name],
    [
      "Period",
      `${fact.period_label} · ${PERIOD_TYPE[fact.period_type]}${fact.period_end ? ` ending ${fact.period_end}` : ""}`,
    ],
    ["Value as printed", fact.original_text],
    ["Column", fact.evidence.header],
    ["Unit statement", fact.evidence.unit],
    ["Scale", fact.scale],
    ["Currency", fact.currency ?? "Not stated"],
    ["Normalized value", formatExact(fact.value, fact.currency)],
    [
      "Status",
      fact.status === "accepted"
        ? "Accepted as a fact"
        : `Needs review: ${fact.review_reasons.join("; ")}`,
    ],
    ["Extraction", `Deterministic parser (${fact.evidence.kind.replace("_", " ")}), no AI`],
  ];

  return (
    <div className="space-y-6">
      {back}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Evidence explorer</h1>
        <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
          <FactBadge /> {fact.metric_name}, {fact.period_label}:{" "}
          <span className="font-medium text-slate-900">
            {formatExact(fact.value, fact.currency)}
          </span>
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[22rem_1fr]">
        <aside aria-label="Source details" className="space-y-3 text-sm">
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Source text
            </h2>
            <p className="mt-1 break-words rounded border-l-4 border-fact bg-slate-50 px-2 py-1 font-mono text-xs">
              {fact.evidence.content}
            </p>
          </div>
          <dl className="grid grid-cols-[8rem_1fr] gap-x-3 gap-y-1">
            {rows
              .filter(([, v]) => v)
              .map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-slate-500">{k}</dt>
                  <dd className="break-words">{v}</dd>
                </div>
              ))}
          </dl>
          <p className="text-xs text-slate-500">
            Source page {fact.evidence.page_number}: the row is highlighted in the page&apos;s
            extracted text. The PDF itself is not annotated.
          </p>
        </aside>

        <PageViewer
          documentId={documentId}
          page={page}
          onPageChange={setPage}
          highlight={page === fact.evidence.page_number ? fact.evidence.content : null}
        />
      </div>
    </div>
  );
}
