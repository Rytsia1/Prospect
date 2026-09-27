"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { CalculationsPanel } from "@/components/calculations-panel";
import { EvidenceCard, FactsPanel } from "@/components/facts-panel";
import { PageViewer } from "@/components/page-viewer";
import { StatusBadge } from "@/components/status-badge";
import { ApiError, api } from "@/lib/api";
import {
  DOCUMENT_TYPE_LABEL,
  type FinancialFact,
  formatBytes,
  formatDate,
  isSettled,
  type ProspectDocument,
} from "@/lib/documents";

const POLL_MS = 5000;

export function DocumentDetail({ id, initialPage }: { id: string; initialPage: number }) {
  const [document, setDocument] = useState<ProspectDocument | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [opening, setOpening] = useState(false);
  const router = useRouter();
  const [page, setPage] = useState(initialPage);
  const [evidence, setEvidence] = useState<FinancialFact | null>(null);

  function goToPage(n: number) {
    setPage(n);
    router.replace(`?page=${n}`, { scroll: false }); // shareable link to this page
  }

  function showEvidence(fact: FinancialFact) {
    setEvidence(fact);
    goToPage(fact.evidence.page_number);
    window.document.getElementById("evidence-view")?.scrollIntoView({ behavior: "smooth" });
  }

  const load = useCallback(async () => {
    try {
      setDocument(await api<ProspectDocument>(`/documents/${id}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Could not load document."));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const active = document ? !isSettled(document.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  async function openPdf() {
    setOpening(true);
    try {
      const { url } = await api<{ url: string }>(`/documents/${id}/download-url`);
      window.open(url, "_blank", "noopener");
    } catch (e) {
      setError(e instanceof ApiError ? e : null);
    } finally {
      setOpening(false);
    }
  }

  const back = (
    <Link href="/documents" className="text-sm text-slate-600 hover:text-slate-900">
      ← Documents
    </Link>
  );

  if (error?.status === 404) {
    return (
      <div className="space-y-3">
        {back}
        <h1 className="text-xl font-semibold">Not found</h1>
        <p className="text-sm text-slate-600">This document does not exist.</p>
      </div>
    );
  }
  if (!document) {
    return (
      <div className="space-y-3">
        {back}
        {error ? (
          <p role="alert" className="text-sm text-red-800">
            {error.message}{" "}
            <button type="button" onClick={load} className="underline">
              Try again
            </button>
          </p>
        ) : (
          <p role="status" className="text-sm text-slate-500">
            Loading…
          </p>
        )}
      </div>
    );
  }

  const fileAvailable = document.status !== "UPLOADING" && document.status !== "FAILED";
  const rows: [string, string][] = [
    ["Type", DOCUMENT_TYPE_LABEL[document.document_type]],
    ["Fiscal year", document.fiscal_year ? `FY${document.fiscal_year}` : "Not specified"],
    ["Size", formatBytes(document.size_bytes)],
    ["Format", document.mime_type],
    ["Uploaded", formatDate(document.created_at)],
    ["Last updated", formatDate(document.updated_at)],
    ["Document ID", document.id],
  ];

  return (
    <div className="space-y-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <h1 className="break-words text-2xl font-semibold tracking-tight">{document.filename}</h1>
          <StatusBadge status={document.status} />
        </div>
        {fileAvailable && (
          <button
            type="button"
            onClick={openPdf}
            disabled={opening}
            className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {opening ? "Opening…" : "Open PDF"}
          </button>
        )}
      </div>

      {document.status === "FAILED" && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-900"
        >
          <p className="font-medium">Processing failed</p>
          <p className="mt-1">{document.processing_error ?? "No error details were recorded."}</p>
        </div>
      )}
      {error && error.status !== 404 && (
        <p role="alert" className="text-sm text-red-800">
          {error.message}
        </p>
      )}

      <dl className="grid max-w-2xl grid-cols-[10rem_1fr] gap-x-4 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-slate-500">{label}</dt>
            <dd className="break-all">{value}</dd>
          </div>
        ))}
      </dl>

      {document.status === "READY" ? (
        <>
          <FactsPanel documentId={document.id} onShowEvidence={showEvidence} />
          <CalculationsPanel documentId={document.id} onShowEvidence={showEvidence} />
          <div id="evidence-view" className="scroll-mt-4 space-y-3">
            {evidence && <EvidenceCard fact={evidence} onClose={() => setEvidence(null)} />}
            <PageViewer
              documentId={document.id}
              page={page}
              onPageChange={goToPage}
              highlight={evidence?.evidence.page_number === page ? evidence.evidence.content : null}
            />
          </div>
        </>
      ) : (
        document.status !== "FAILED" && (
          <p className="text-sm text-slate-500">
            Extracted pages appear here once processing finishes.
          </p>
        )
      )}
    </div>
  );
}
