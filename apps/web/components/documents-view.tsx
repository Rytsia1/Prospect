"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { StatusBadge } from "@/components/status-badge";
import { Upload } from "@/components/upload";
import { ApiError, api } from "@/lib/api";
import {
  DOCUMENT_TYPE_LABEL,
  formatBytes,
  formatDate,
  isSettled,
  type ProspectDocument,
} from "@/lib/documents";

const POLL_MS = 5000;

export function DocumentsView() {
  const [documents, setDocuments] = useState<ProspectDocument[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const { items } = await api<{ items: ProspectDocument[] }>("/documents");
      setDocuments(items);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load documents.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Poll only while something is still moving through the pipeline.
  const active = documents?.some((d) => !isSettled(d.status)) ?? false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
      <Upload onUploaded={load} />

      <section aria-labelledby="list-heading" className="space-y-3">
        <h2
          id="list-heading"
          className="text-sm font-semibold uppercase tracking-wide text-slate-500"
        >
          Your documents
        </h2>
        {error && (
          <div role="alert" className="flex items-center gap-3 text-sm text-red-800">
            {error}
            <button type="button" onClick={load} className="underline">
              Try again
            </button>
          </div>
        )}
        {documents === null && !error && (
          <p role="status" className="text-sm text-slate-500">
            Loading…
          </p>
        )}
        {documents?.length === 0 && (
          <div className="rounded border border-dashed border-slate-300 px-6 py-12 text-center">
            <p className="font-medium">No documents yet.</p>
            <p className="mt-1 text-sm text-slate-600">
              Upload an annual report to start researching.
            </p>
          </div>
        )}
        {documents && documents.length > 0 && (
          <ul className="divide-y divide-slate-200 rounded border border-slate-200">
            {documents.map((d) => (
              <li key={d.id}>
                <Link
                  href={`/documents/${d.id}`}
                  className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 hover:bg-slate-50"
                >
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{d.filename}</span>
                    <span className="block text-xs text-slate-500">
                      {DOCUMENT_TYPE_LABEL[d.document_type]}
                      {d.fiscal_year ? ` · FY${d.fiscal_year}` : ""} · {formatBytes(d.size_bytes)} ·
                      Uploaded {formatDate(d.created_at)}
                    </span>
                  </span>
                  <StatusBadge status={d.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
