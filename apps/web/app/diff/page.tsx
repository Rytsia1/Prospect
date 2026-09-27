"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { formatAmount, type ProspectDocument } from "@/lib/documents";
import { compareDocuments, type DocumentDiffResponse, sectionDiffBadge } from "@/lib/phase6";

export default function DiffPage() {
  const [documents, setDocuments] = useState<ProspectDocument[]>([]);
  const [docAId, setDocAId] = useState<string>("");
  const [docBId, setDocBId] = useState<string>("");
  const [loadingDocs, setLoadingDocs] = useState(true);

  const [diffResult, setDiffResult] = useState<DocumentDiffResponse | null>(null);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Tabs: financial, section, text
  const [activeTab, setActiveTab] = useState<"financial" | "section" | "text">("financial");

  const loadDocuments = useCallback(async () => {
    try {
      setLoadingDocs(true);
      const res = await api<{ items: ProspectDocument[] }>("/documents");
      const readyDocs = res.items.filter((d) => d.status === "READY");
      setDocuments(readyDocs);
      if (readyDocs.length >= 2) {
        setDocAId(readyDocs[1].id);
        setDocBId(readyDocs[0].id);
      } else if (readyDocs.length === 1) {
        setDocAId(readyDocs[0].id);
        setDocBId(readyDocs[0].id);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load documents.");
    } finally {
      setLoadingDocs(false);
    }
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleCompare = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docAId || !docBId) return;
    try {
      setComparing(true);
      setError(null);
      const res = await compareDocuments(docAId, docBId);
      setDiffResult(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to compare documents.");
    } finally {
      setComparing(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Document Diff</h1>
        <p className="text-sm text-slate-500">
          Deterministic side-by-side comparison of metadata, structured financial facts, sections,
          and unified text.
        </p>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {/* Selectors Bar */}
      <form onSubmit={handleCompare} className="rounded-lg border border-slate-200 bg-slate-50 p-4">
        {loadingDocs ? (
          <div className="py-2 text-xs text-slate-500">Loading documents for comparison...</div>
        ) : documents.length < 2 ? (
          <div className="py-2 text-xs text-slate-600">
            At least two processed documents are needed to perform a document diff. You currently
            have {documents.length} ready document(s).
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[240px]">
              <label
                htmlFor="doc-a"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
              >
                Document A (Baseline / Older)
              </label>
              <select
                id="doc-a"
                value={docAId}
                onChange={(e) => setDocAId(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename} {d.fiscal_year ? `(FY${d.fiscal_year})` : ""}
                  </option>
                ))}
              </select>
            </div>

            <div className="text-sm font-semibold text-slate-400 pb-2">VS</div>

            <div className="flex-1 min-w-[240px]">
              <label
                htmlFor="doc-b"
                className="block text-xs font-semibold uppercase tracking-wider text-slate-700"
              >
                Document B (Target / Newer)
              </label>
              <select
                id="doc-b"
                value={docBId}
                onChange={(e) => setDocBId(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 bg-white px-3 py-2 text-sm"
              >
                {documents.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.filename} {d.fiscal_year ? `(FY${d.fiscal_year})` : ""}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <button
                type="submit"
                disabled={comparing || !docAId || !docBId}
                className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:opacity-50"
              >
                {comparing ? "Comparing..." : "Compare Documents"}
              </button>
            </div>
          </div>
        )}
      </form>

      {/* Comparison Results */}
      {diffResult && (
        <div className="space-y-6">
          {/* Metadata Comparison Summary */}
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="text-sm font-semibold text-slate-800 mb-2">Metadata Comparison</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-xs">
              <div className="rounded border border-slate-100 bg-slate-50 p-3">
                <div className="font-semibold text-slate-700">Document A</div>
                <div className="mt-1 text-slate-900 font-medium">{diffResult.doc_a.filename}</div>
                <div className="text-slate-500">
                  Fiscal Year: {diffResult.doc_a.fiscal_year || "—"} | Company:{" "}
                  {diffResult.doc_a.company_name || "—"}
                </div>
              </div>
              <div className="rounded border border-slate-100 bg-slate-50 p-3">
                <div className="font-semibold text-slate-700">Document B</div>
                <div className="mt-1 text-slate-900 font-medium">{diffResult.doc_b.filename}</div>
                <div className="text-slate-500">
                  Fiscal Year: {diffResult.doc_b.fiscal_year || "—"} | Company:{" "}
                  {diffResult.doc_b.company_name || "—"}
                </div>
              </div>
            </div>

            {diffResult.metadata_diff.notes.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {diffResult.metadata_diff.notes.map((note) => (
                  <span
                    key={note}
                    className="rounded bg-slate-100 px-2 py-0.5 text-xs text-slate-600"
                  >
                    ℹ {note}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Navigation Tabs */}
          <div className="flex border-b border-slate-200">
            <button
              type="button"
              onClick={() => setActiveTab("financial")}
              className={`border-b-2 px-4 py-2 text-sm font-medium ${
                activeTab === "financial"
                  ? "border-slate-900 text-slate-900 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              Financial Changes ({diffResult.financial_diff.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("section")}
              className={`border-b-2 px-4 py-2 text-sm font-medium ${
                activeTab === "section"
                  ? "border-slate-900 text-slate-900 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              Section Changes ({diffResult.section_diff.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveTab("text")}
              className={`border-b-2 px-4 py-2 text-sm font-medium ${
                activeTab === "text"
                  ? "border-slate-900 text-slate-900 font-semibold"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              Text Changes ({diffResult.text_diff.length})
            </button>
          </div>

          {/* Tab 1: Financial Diff */}
          {activeTab === "financial" && (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Metric</th>
                    <th className="px-4 py-3 text-right">Document A Value</th>
                    <th className="px-4 py-3 text-right">Document B Value</th>
                    <th className="px-4 py-3 text-right">Deterministic Change</th>
                    <th className="px-4 py-3">Evidence Doc A</th>
                    <th className="px-4 py-3">Evidence Doc B</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {diffResult.financial_diff.map((item) => (
                    <tr key={item.metric} className="hover:bg-slate-50">
                      <td className="px-4 py-3 font-medium text-slate-900">{item.metric_name}</td>
                      <td className="px-4 py-3 text-right font-medium text-slate-700">
                        {item.val_a ? formatAmount(item.val_a, item.currency) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right font-medium text-slate-900">
                        {item.val_b ? formatAmount(item.val_b, item.currency) : "—"}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {item.change_pct ? (
                          <span
                            className={`font-semibold ${
                              item.change_pct.startsWith("-") ? "text-rose-600" : "text-emerald-600"
                            }`}
                          >
                            {item.change_pct.startsWith("-") ? "" : "+"}
                            {item.change_pct}%
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {item.evidence_a ? (
                          <Link
                            href={`/documents/${diffResult.doc_a.id}?page=${item.evidence_a.page_number}`}
                            className="text-blue-600 hover:underline"
                          >
                            Page {item.evidence_a.page_number}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-3 text-xs text-slate-500">
                        {item.evidence_b ? (
                          <Link
                            href={`/documents/${diffResult.doc_b.id}?page=${item.evidence_b.page_number}`}
                            className="text-blue-600 hover:underline"
                          >
                            Page {item.evidence_b.page_number}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Tab 2: Section Diff */}
          {activeTab === "section" && (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-left text-sm">
                <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
                  <tr>
                    <th className="px-4 py-3">Section Title</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3 text-right">Page in A</th>
                    <th className="px-4 py-3 text-right">Page in B</th>
                    <th className="px-4 py-3 text-right">Char Diff</th>
                    <th className="px-4 py-3">Certainty</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200">
                  {diffResult.section_diff.map((s) => {
                    const badge = sectionDiffBadge(s.status);
                    return (
                      <tr key={s.section_title} className="hover:bg-slate-50">
                        <td className="px-4 py-3 font-medium text-slate-900">{s.section_title}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${badge.className}`}
                          >
                            <span>{badge.symbol}</span>
                            <span>{badge.label}</span>
                          </span>
                        </td>
                        <td className="px-4 py-3 text-right text-slate-600">
                          {s.page_a !== null ? `p. ${s.page_a}` : "—"}
                        </td>
                        <td className="px-4 py-3 text-right text-slate-600">
                          {s.page_b !== null ? `p. ${s.page_b}` : "—"}
                        </td>
                        <td className="px-4 py-3 text-right font-mono text-xs">
                          {s.char_diff > 0 ? `+${s.char_diff}` : s.char_diff}
                        </td>
                        <td className="px-4 py-3 text-xs">
                          {s.uncertain ? (
                            <span className="rounded bg-amber-50 px-2 py-0.5 text-amber-700 font-medium">
                              ⚠ Uncertain Match
                            </span>
                          ) : (
                            <span className="text-slate-400">Deterministic</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {/* Tab 3: Unified Text Diff */}
          {activeTab === "text" && (
            <div className="space-y-4">
              {diffResult.text_diff.map((td) => (
                <div
                  key={td.section_title}
                  className="rounded-lg border border-slate-200 bg-white p-4"
                >
                  <div className="flex items-center justify-between pb-2 border-b border-slate-100">
                    <h3 className="text-sm font-semibold text-slate-900">{td.section_title}</h3>
                    <span className="text-xs uppercase text-slate-500 font-medium">
                      {td.status}
                    </span>
                  </div>

                  {td.unified_diff.length === 0 ? (
                    <div className="py-4 text-xs text-slate-400">
                      No textual differences found in this section.
                    </div>
                  ) : (
                    <pre className="mt-3 max-h-64 overflow-auto rounded bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-200">
                      {td.unified_diff.map((line, lIdx) => (
                        <div
                          // biome-ignore lint/suspicious/noArrayIndexKey: diff lines have no natural id other than line position
                          key={`${td.section_title}-${line}-${lIdx}`}
                          className={
                            line.startsWith("+")
                              ? "text-emerald-400"
                              : line.startsWith("-")
                                ? "text-rose-400"
                                : line.startsWith("@@")
                                  ? "text-blue-400"
                                  : "text-slate-400"
                          }
                        >
                          {line}
                        </div>
                      ))}
                    </pre>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
