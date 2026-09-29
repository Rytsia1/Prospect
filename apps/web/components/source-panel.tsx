"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { EvidenceCard } from "@/components/facts-panel";
import { PageViewer } from "@/components/page-viewer";
import type { FinancialFact } from "@/lib/documents";
import { evidencePath } from "@/lib/financials";

/** A fact's source beside the numbers (docs/UX_SPEC.md §5): the evidence and its page, without
 * leaving the table being checked. A right-hand column on wide screens, a bottom sheet on
 * narrow ones. Escape closes it and focus returns to the fact that opened it. */
export function SourcePanel({ fact, onClose }: { fact: FinancialFact; onClose: () => void }) {
  const [page, setPage] = useState(fact.evidence.page_number);
  const panel = useRef<HTMLElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const opener = useRef<Element | null>(null);

  useEffect(() => {
    setPage(fact.evidence.page_number);
    const active = globalThis.document?.activeElement;
    if (active && !panel.current?.contains(active)) opener.current = active; // the fact clicked
    heading.current?.focus({ preventScroll: true });
  }, [fact]);

  useEffect(() => {
    return () => {
      if (opener.current instanceof HTMLElement && opener.current.isConnected) {
        opener.current.focus();
      }
    };
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <aside
      ref={panel}
      aria-labelledby="source-panel-heading"
      className="fixed inset-x-0 bottom-0 z-20 max-h-[70vh] space-y-3 overflow-y-auto rounded-t-lg border-t border-slate-200 bg-surface p-4 shadow-2xl lg:sticky lg:top-4 lg:right-auto lg:bottom-auto lg:left-auto lg:z-auto lg:max-h-[calc(100vh-2rem)] lg:rounded lg:border lg:shadow-none"
    >
      <div className="flex items-baseline justify-between gap-3">
        <h2
          id="source-panel-heading"
          ref={heading}
          tabIndex={-1}
          className="text-xs font-semibold uppercase tracking-wide text-slate-500 focus:outline-none"
        >
          Source
        </h2>
        <Link href={evidencePath(fact)} className="text-xs text-slate-600 underline">
          Open full page
        </Link>
      </div>
      <EvidenceCard fact={fact} onClose={onClose} />
      <PageViewer
        documentId={fact.document_id}
        page={page}
        onPageChange={setPage}
        highlight={page === fact.evidence.page_number ? fact.evidence.content : null}
        compact
      />
    </aside>
  );
}
