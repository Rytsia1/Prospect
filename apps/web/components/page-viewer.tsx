"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import {
  type DocumentPage,
  type DocumentSection,
  type PageSummary,
  printedLabel,
} from "@/lib/documents";

type Props = { documentId: string; initialPage: number };

export function PageViewer({ documentId, initialPage }: Props) {
  const router = useRouter();
  const [pages, setPages] = useState<PageSummary[] | null>(null);
  const [sections, setSections] = useState<DocumentSection[]>([]);
  const [current, setCurrent] = useState(initialPage);
  const [page, setPage] = useState<DocumentPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      api<{ items: PageSummary[] }>(`/documents/${documentId}/pages`),
      api<{ items: DocumentSection[] }>(`/documents/${documentId}/sections`),
    ])
      .then(([p, s]) => {
        setPages(p.items);
        setSections(s.items);
      })
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not load pages."));
  }, [documentId]);

  const total = pages?.length ?? 0;
  const pageNumber = total ? Math.min(Math.max(current, 1), total) : current;

  useEffect(() => {
    if (!total) return;
    let cancelled = false;
    setPage(null);
    api<DocumentPage>(`/documents/${documentId}/pages/${pageNumber}`)
      .then((p) => !cancelled && setPage(p))
      .catch((e) => !cancelled && setError(e instanceof ApiError ? e.message : "Page failed."));
    return () => {
      cancelled = true;
    };
  }, [documentId, pageNumber, total]);

  function go(n: number) {
    setCurrent(n);
    router.replace(`?page=${n}`, { scroll: false }); // shareable link to this page
  }

  if (error) {
    return (
      <p role="alert" className="text-sm text-red-800">
        {error}
      </p>
    );
  }
  if (!pages) {
    return (
      <p role="status" className="text-sm text-slate-500">
        Loading pages…
      </p>
    );
  }

  const inSection = (s: DocumentSection) => s.start_page <= pageNumber && pageNumber <= s.end_page;
  const label = page ? printedLabel(page) : null;

  return (
    <div className="grid gap-6 lg:grid-cols-[16rem_1fr]">
      <nav aria-label="Document navigation" className="space-y-5 text-sm">
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Sections
          </h2>
          <ul className="max-h-64 space-y-0.5 overflow-y-auto lg:max-h-80">
            {sections.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  onClick={() => go(s.start_page)}
                  aria-current={inSection(s) ? "location" : undefined}
                  className={`w-full rounded px-2 py-1 text-left hover:bg-slate-50 ${
                    inSection(s) ? "bg-slate-100" : ""
                  }`}
                >
                  <span className={`block truncate ${s.title ? "" : "italic text-slate-500"}`}>
                    {s.title ?? "Untitled section"}
                  </span>
                  <span className="block text-xs text-slate-500">
                    {s.start_page === s.end_page
                      ? `Page ${s.start_page}`
                      : `Pages ${s.start_page}–${s.end_page}`}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Pages
          </h2>
          <ul className="grid max-h-80 grid-cols-3 gap-1 overflow-y-auto sm:grid-cols-6 lg:grid-cols-2">
            {pages.map((p) => (
              <li key={p.page_number}>
                <button
                  type="button"
                  onClick={() => go(p.page_number)}
                  aria-current={p.page_number === pageNumber ? "page" : undefined}
                  title={p.char_count === 0 ? "No extracted text" : undefined}
                  className={`w-full rounded border px-2 py-1 text-left ${
                    p.page_number === pageNumber
                      ? "border-slate-900 bg-slate-900 text-white"
                      : "border-slate-200 hover:bg-slate-50"
                  } ${p.char_count === 0 ? "text-slate-400" : ""}`}
                >
                  Page {p.page_number}
                </button>
              </li>
            ))}
          </ul>
        </div>
      </nav>

      <section aria-labelledby="page-heading" className="min-w-0 rounded border border-slate-200">
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-4 py-2">
          <h2 id="page-heading" className="font-medium">
            Page {pageNumber} <span className="font-normal text-slate-500">of {total}</span>
            {label && (
              <span className="ml-2 text-sm font-normal text-slate-500">
                · printed page {label}
              </span>
            )}
          </h2>
          <div className="flex gap-2 text-sm">
            <button
              type="button"
              onClick={() => go(pageNumber - 1)}
              disabled={pageNumber <= 1}
              className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-50 disabled:opacity-40"
            >
              Previous
            </button>
            <button
              type="button"
              onClick={() => go(pageNumber + 1)}
              disabled={pageNumber >= total}
              className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-50 disabled:opacity-40"
            >
              Next
            </button>
          </div>
        </header>
        <div className="px-4 py-4">
          {!page ? (
            <p role="status" className="text-sm text-slate-500">
              Loading page…
            </p>
          ) : page.text ? (
            <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-relaxed">
              {page.text}
            </pre>
          ) : (
            <p className="text-sm text-slate-600">
              {page.extraction_status === "partial"
                ? "This page contains images but no text layer (for example a scanned page). OCR is not supported yet, so its content is not available."
                : page.extraction_status === "failed"
                  ? "Text extraction failed for this page."
                  : "This page has no text."}
            </p>
          )}
        </div>
      </section>
    </div>
  );
}
