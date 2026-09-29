"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/documents";
import { listWatchlist, removeFromWatchlist, type WatchlistEntry } from "@/lib/phase6";

export default function WatchlistPage() {
  const [entries, setEntries] = useState<WatchlistEntry[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listWatchlist();
      setEntries(res);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load watchlist.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleRemove = async (companyId: string) => {
    try {
      await removeFromWatchlist(companyId);
      setEntries((prev) => (prev ? prev.filter((e) => e.company_id !== companyId) : null));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to remove company from watchlist.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Watchlist</h1>
          <p className="text-sm text-slate-500">
            Factual research bookmarking. Financial values derive strictly from canonical facts.
          </p>
        </div>
        <Link
          href="/companies"
          className="rounded border border-slate-300 bg-surface px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          Manage Companies →
        </Link>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500">Loading watchlist...</div>
      ) : entries && entries.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">★</th>
                <th className="px-4 py-3">Company</th>
                <th className="px-4 py-3">Currency</th>
                <th className="px-4 py-3 text-right">Latest Period</th>
                <th className="px-4 py-3 text-right">Latest Revenue</th>
                <th className="px-4 py-3 text-right">Latest Net Income</th>
                <th className="px-4 py-3 text-right">Revenue YoY</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {entries.map((item) => (
                <tr key={item.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3 text-amber-500">★</td>
                  <td className="px-4 py-3">
                    <Link
                      href={`/companies/${item.company_id}`}
                      className="font-medium text-slate-900 hover:underline"
                    >
                      {item.company_name}
                    </Link>
                    {item.ticker && (
                      <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {item.ticker}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-slate-600">{item.currency}</td>
                  <td className="px-4 py-3 text-right text-slate-600">
                    {item.latest_period || "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-medium">
                    {item.latest_revenue ? formatAmount(item.latest_revenue, item.currency) : "—"}
                  </td>
                  <td className="px-4 py-3 text-right font-medium">
                    {item.latest_net_income
                      ? formatAmount(item.latest_net_income, item.currency)
                      : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    {item.revenue_yoy_pct ? (
                      <span
                        className={`font-medium ${
                          item.revenue_yoy_pct.startsWith("-")
                            ? "text-rose-600"
                            : "text-emerald-600"
                        }`}
                      >
                        {item.revenue_yoy_pct.startsWith("-") ? "" : "+"}
                        {item.revenue_yoy_pct}%
                      </span>
                    ) : (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      <Link
                        href={`/companies/${item.company_id}`}
                        className="rounded border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                      >
                        Open Workspace
                      </Link>
                      <button
                        type="button"
                        onClick={() => handleRemove(item.company_id)}
                        className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-100 hover:text-red-600"
                        title="Remove from watchlist"
                      >
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 py-12 text-center">
          <p className="text-sm text-slate-600">No companies bookmarked in your watchlist.</p>
          <p className="mt-1 text-xs text-slate-400">
            Bookmark companies from the Companies workspace to track them here.
          </p>
          <Link
            href="/companies"
            className="mt-4 inline-block rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover"
          >
            Explore Companies
          </Link>
        </div>
      )}

      <div className="rounded-md border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
        <strong>Factual Note:</strong> Watchlist metrics show reported financial values and
        deterministic historical changes. Prospect does not provide buy/sell signals or subjective
        investment opinions.
      </div>
    </div>
  );
}
