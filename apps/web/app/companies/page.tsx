"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/documents";
import {
  addToWatchlist,
  type Company,
  createCompany,
  listCompanies,
  listWatchlist,
  removeFromWatchlist,
  type WatchlistEntry,
} from "@/lib/phase6";

export default function CompaniesPage() {
  const [companies, setCompanies] = useState<Company[] | null>(null);
  const [watchlist, setWatchlist] = useState<Set<string>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  // Modal / Form state
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [ticker, setTicker] = useState("");
  const [country, setCountry] = useState("ID");
  const [currency, setCurrency] = useState("IDR");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const loadData = useCallback(async () => {
    try {
      setLoading(true);
      const [comps, wl] = await Promise.all([listCompanies(), listWatchlist()]);
      setCompanies(comps);
      setWatchlist(new Set(wl.map((w: WatchlistEntry) => w.company_id)));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load companies.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      setSubmitting(true);
      await createCompany({
        name: name.trim(),
        ticker: ticker.trim() ? ticker.trim().toUpperCase() : null,
        country: country.trim() ? country.trim().toUpperCase() : null,
        currency: currency.trim() ? currency.trim().toUpperCase() : "IDR",
        description: description.trim() ? description.trim() : null,
      });
      setShowCreate(false);
      setName("");
      setTicker("");
      setDescription("");
      await loadData();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not create company.");
    } finally {
      setSubmitting(false);
    }
  };

  const toggleWatchlist = async (companyId: string) => {
    try {
      if (watchlist.has(companyId)) {
        await removeFromWatchlist(companyId);
        setWatchlist((prev) => {
          const next = new Set(prev);
          next.delete(companyId);
          return next;
        });
      } else {
        await addToWatchlist(companyId);
        setWatchlist((prev) => new Set(prev).add(companyId));
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to update watchlist.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Company Workspaces</h1>
          <p className="text-sm text-slate-500">
            Organize multi-year documents and canonical financial intelligence by company.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
        >
          + New Company
        </button>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {showCreate && (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-4 shadow-xs">
          <h2 className="mb-3 text-base font-medium">Create Company Workspace</h2>
          <form onSubmit={handleCreate} className="space-y-3">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-4">
              <div>
                <label htmlFor="company-name" className="block text-xs font-medium text-slate-700">
                  Company Name *
                </label>
                <input
                  id="company-name"
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Bank Central Asia"
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
              <div>
                <label
                  htmlFor="company-ticker"
                  className="block text-xs font-medium text-slate-700"
                >
                  Ticker Symbol
                </label>
                <input
                  id="company-ticker"
                  type="text"
                  value={ticker}
                  onChange={(e) => setTicker(e.target.value)}
                  placeholder="e.g. BBCA"
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
              <div>
                <label
                  htmlFor="company-country"
                  className="block text-xs font-medium text-slate-700"
                >
                  Country
                </label>
                <input
                  id="company-country"
                  type="text"
                  value={country}
                  onChange={(e) => setCountry(e.target.value)}
                  placeholder="e.g. ID"
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
              <div>
                <label
                  htmlFor="company-currency"
                  className="block text-xs font-medium text-slate-700"
                >
                  Currency
                </label>
                <input
                  id="company-currency"
                  type="text"
                  value={currency}
                  onChange={(e) => setCurrency(e.target.value)}
                  placeholder="e.g. IDR"
                  className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
                />
              </div>
            </div>
            <div>
              <label htmlFor="company-desc" className="block text-xs font-medium text-slate-700">
                Description (Optional)
              </label>
              <input
                id="company-desc"
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief business summary"
                className="mt-1 w-full rounded border border-slate-300 bg-surface px-2.5 py-1.5 text-sm"
              />
            </div>
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting || !name.trim()}
                className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
              >
                {submitting ? "Creating..." : "Save Workspace"}
              </button>
            </div>
          </form>
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500">Loading companies...</div>
      ) : companies && companies.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Watch</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Country / Currency</th>
                <th className="px-4 py-3 text-right">Filings</th>
                <th className="px-4 py-3 text-right">Latest Period</th>
                <th className="px-4 py-3 text-right">Latest Revenue</th>
                <th className="px-4 py-3 text-right">Latest Net Income</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {companies.map((c) => {
                const isWatch = watchlist.has(c.id);
                return (
                  <tr key={c.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={() => toggleWatchlist(c.id)}
                        title={isWatch ? "Remove from watchlist" : "Add to watchlist"}
                        className={`text-base ${isWatch ? "text-amber-500" : "text-slate-300 hover:text-slate-400"}`}
                        aria-label={`Toggle watchlist for ${c.name}`}
                      >
                        {isWatch ? "★" : "☆"}
                      </button>
                    </td>
                    <td className="px-4 py-3">
                      <Link
                        href={`/companies/${c.id}`}
                        className="font-medium text-slate-900 hover:underline"
                      >
                        {c.name}
                      </Link>
                      {c.ticker && (
                        <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                          {c.ticker}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {c.country || "—"} / {c.currency}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">{c.documents?.length || 0}</td>
                    <td className="px-4 py-3 text-right text-slate-600">
                      {c.latest_period || "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {c.latest_revenue ? formatAmount(c.latest_revenue, c.currency) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      {c.latest_net_income ? formatAmount(c.latest_net_income, c.currency) : "—"}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/companies/${c.id}`}
                        className="rounded border border-slate-200 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                      >
                        Open Workspace →
                      </Link>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 py-12 text-center">
          <p className="text-sm text-slate-600">No companies created yet.</p>
          <p className="mt-1 text-xs text-slate-400">
            Create a company workspace to aggregate documents and multi-year financials.
          </p>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="mt-4 rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
          >
            Create your first company
          </button>
        </div>
      )}
    </div>
  );
}
