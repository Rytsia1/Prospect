"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { formatAmount, type ProspectDocument } from "@/lib/documents";
import {
  addToWatchlist,
  attachDocumentToCompany,
  type Company,
  deleteCompany,
  detachDocumentFromCompany,
  getCompany,
  listWatchlist,
  removeFromWatchlist,
  updateCompany,
  type WatchlistEntry,
} from "@/lib/phase6";

export default function CompanyDetailPage() {
  const params = useParams();
  const router = useRouter();
  const companyId = params?.id as string;

  const [company, setCompany] = useState<Company | null>(null);
  const [allDocs, setAllDocs] = useState<ProspectDocument[]>([]);
  const [isWatchlist, setIsWatchlist] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Attach modal state
  const [showAttach, setShowAttach] = useState(false);
  const [selectedDocId, setSelectedDocId] = useState("");
  const [attaching, setAttaching] = useState(false);

  // Edit modal state
  const [showEdit, setShowEdit] = useState(false);
  const [editName, setEditName] = useState("");
  const [editTicker, setEditTicker] = useState("");
  const [editDesc, setEditDesc] = useState("");

  const load = useCallback(async () => {
    if (!companyId) return;
    try {
      setLoading(true);
      const [comp, wl, docsRes] = await Promise.all([
        getCompany(companyId),
        listWatchlist(),
        api<{ items: ProspectDocument[] }>("/documents"),
      ]);
      setCompany(comp);
      setIsWatchlist(wl.some((w: WatchlistEntry) => w.company_id === companyId));
      setAllDocs(docsRes.items);
      setEditName(comp.name);
      setEditTicker(comp.ticker || "");
      setEditDesc(comp.description || "");
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load company workspace.");
    } finally {
      setLoading(false);
    }
  }, [companyId]);

  useEffect(() => {
    load();
  }, [load]);

  const handleToggleWatchlist = async () => {
    if (!company) return;
    try {
      if (isWatchlist) {
        await removeFromWatchlist(company.id);
        setIsWatchlist(false);
      } else {
        await addToWatchlist(company.id);
        setIsWatchlist(true);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to update watchlist.");
    }
  };

  const handleAttach = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedDocId || !company) return;
    try {
      setAttaching(true);
      await attachDocumentToCompany(company.id, selectedDocId);
      setShowAttach(false);
      setSelectedDocId("");
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not attach document.");
    } finally {
      setAttaching(false);
    }
  };

  const handleDetach = async (docId: string) => {
    if (!company) return;
    if (!confirm("Are you sure you want to detach this document from this workspace?")) return;
    try {
      await detachDocumentFromCompany(company.id, docId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not detach document.");
    }
  };

  const handleUpdate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!company) return;
    try {
      await updateCompany(company.id, {
        name: editName.trim(),
        ticker: editTicker.trim() ? editTicker.trim().toUpperCase() : null,
        description: editDesc.trim() ? editDesc.trim() : null,
      });
      setShowEdit(false);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update company.");
    }
  };

  const handleDelete = async () => {
    if (!company) return;
    if (
      !confirm(
        "Delete this company workspace? The documents will NOT be deleted; they will be detached into standalone documents.",
      )
    )
      return;
    try {
      await deleteCompany(company.id);
      router.push("/companies");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not delete company.");
    }
  };

  if (loading) {
    return (
      <div className="py-12 text-center text-sm text-slate-500">Loading company workspace...</div>
    );
  }

  if (!company) {
    return (
      <div className="py-12 text-center text-sm text-red-600">
        Company not found.{" "}
        <Link href="/companies" className="underline">
          Back to companies
        </Link>
      </div>
    );
  }

  // Filter unattached documents for attachment
  const attachedDocIds = new Set(company.documents.map((d) => d.id));
  const unattachedDocs = allDocs.filter((d) => !attachedDocIds.has(d.id));

  return (
    <div className="space-y-8">
      {/* Breadcrumb & Header */}
      <div>
        <div className="mb-2">
          <Link href="/companies" className="text-xs text-slate-500 hover:text-slate-800">
            ← All Companies
          </Link>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{company.name}</h1>
            {company.ticker && (
              <span className="rounded bg-slate-100 px-2 py-0.5 font-mono text-sm font-medium text-slate-700">
                {company.ticker}
              </span>
            )}
            <button
              type="button"
              onClick={handleToggleWatchlist}
              className={`rounded border px-2.5 py-1 text-xs font-medium ${
                isWatchlist
                  ? "border-amber-300 bg-amber-50 text-amber-800"
                  : "border-slate-300 bg-surface text-slate-700 hover:bg-slate-50"
              }`}
            >
              {isWatchlist ? "★ On Watchlist" : "☆ Add to Watchlist"}
            </button>
          </div>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => setShowEdit(true)}
              className="rounded border border-slate-300 px-3 py-1.5 text-xs font-medium hover:bg-slate-50"
            >
              Edit Details
            </button>
            <button
              type="button"
              onClick={handleDelete}
              className="rounded border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
            >
              Delete Workspace
            </button>
          </div>
        </div>
        {company.description && (
          <p className="mt-2 text-sm text-slate-600">{company.description}</p>
        )}
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {/* Edit Modal */}
      {showEdit && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 shadow-xs">
          <h2 className="mb-3 text-base font-medium">Edit Company Details</h2>
          <form onSubmit={handleUpdate} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label htmlFor="edit-name" className="block text-xs font-medium text-slate-700">
                  Company Name
                </label>
                <input
                  id="edit-name"
                  type="text"
                  required
                  value={editName}
                  onChange={(e) => setEditName(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
              <div>
                <label htmlFor="edit-ticker" className="block text-xs font-medium text-slate-700">
                  Ticker
                </label>
                <input
                  id="edit-ticker"
                  type="text"
                  value={editTicker}
                  onChange={(e) => setEditTicker(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
            </div>
            <div>
              <label htmlFor="edit-desc" className="block text-xs font-medium text-slate-700">
                Description
              </label>
              <input
                id="edit-desc"
                type="text"
                value={editDesc}
                onChange={(e) => setEditDesc(e.target.value)}
                className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowEdit(false)}
                className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
              >
                Save Changes
              </button>
            </div>
          </form>
        </div>
      )}

      {/* KPI Cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
          <div className="text-xs uppercase text-slate-500">Filings Attached</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">
            {company.documents.length}
          </div>
          <div className="mt-1 text-xs text-slate-400">Total documents</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
          <div className="text-xs uppercase text-slate-500">Latest Reported Period</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">
            {company.latest_period || "—"}
          </div>
          <div className="mt-1 text-xs text-slate-400">Most recent fiscal period</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
          <div className="text-xs uppercase text-slate-500">Latest Revenue</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">
            {company.latest_revenue ? formatAmount(company.latest_revenue, company.currency) : "—"}
          </div>
          <div className="mt-1 text-xs text-slate-400">Canonical reported fact</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
          <div className="text-xs uppercase text-slate-500">Latest Net Income</div>
          <div className="mt-1 text-2xl font-semibold tracking-tight">
            {company.latest_net_income
              ? formatAmount(company.latest_net_income, company.currency)
              : "—"}
          </div>
          <div className="mt-1 text-xs text-slate-400">Canonical reported fact</div>
        </div>
      </div>

      {/* Quick Action Navigation */}
      <div className="flex flex-wrap gap-2 text-xs">
        <Link
          href={`/data-quality?company_id=${company.id}`}
          className="rounded border border-slate-200 bg-surface px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
        >
          Check Company Data Quality →
        </Link>
        <Link
          href={`/scenarios?company_id=${company.id}`}
          className="rounded border border-slate-200 bg-surface px-3 py-1.5 font-medium text-slate-700 hover:bg-slate-50"
        >
          Model Scenarios for {company.name} →
        </Link>
      </div>

      {/* Associated Documents Timeline */}
      <section className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-base font-semibold tracking-tight">Document Timeline</h2>
          <button
            type="button"
            onClick={() => setShowAttach(true)}
            className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
          >
            + Attach Document
          </button>
        </div>

        {showAttach && (
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-4">
            <h3 className="mb-2 text-sm font-medium">Attach an Existing Document</h3>
            {unattachedDocs.length === 0 ? (
              <p className="text-xs text-slate-500">
                All your existing documents are already attached to this workspace, or you have no
                documents uploaded.
              </p>
            ) : (
              <form onSubmit={handleAttach} className="flex flex-wrap items-center gap-2">
                <select
                  value={selectedDocId}
                  onChange={(e) => setSelectedDocId(e.target.value)}
                  className="rounded border border-slate-300 bg-surface px-3 py-1.5 text-sm"
                  required
                >
                  <option value="">Select a document...</option>
                  {unattachedDocs.map((d) => (
                    <option key={d.id} value={d.id}>
                      {d.filename} {d.fiscal_year ? `(FY${d.fiscal_year})` : ""}
                    </option>
                  ))}
                </select>
                <button
                  type="submit"
                  disabled={attaching || !selectedDocId}
                  className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
                >
                  {attaching ? "Attaching..." : "Attach to Company"}
                </button>
                <button
                  type="button"
                  onClick={() => setShowAttach(false)}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100"
                >
                  Cancel
                </button>
              </form>
            )}
          </div>
        )}

        {company.documents.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-slate-200">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
                <tr>
                  <th className="px-4 py-3">Fiscal Year</th>
                  <th className="px-4 py-3">Document Filename</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {company.documents.map((doc) => (
                  <tr key={doc.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-semibold text-slate-900">
                      {doc.fiscal_year ? `FY${doc.fiscal_year}` : "—"}
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/documents/${doc.id}`}
                        className="font-medium text-slate-900 hover:underline"
                      >
                        {doc.filename}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
                        {doc.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-2">
                        <Link
                          href={`/documents/${doc.id}`}
                          className="rounded border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                        >
                          View Document →
                        </Link>
                        <button
                          type="button"
                          onClick={() => handleDetach(doc.id)}
                          className="rounded border border-red-200 px-2 py-1 text-xs font-medium text-red-600 hover:bg-red-50"
                        >
                          Detach
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-slate-300 py-8 text-center text-xs text-slate-500">
            No filings attached to this company workspace yet. Click &quot;+ Attach Document&quot;
            above to link reports.
          </div>
        )}
      </section>
    </div>
  );
}
