"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { formatAmount } from "@/lib/documents";
import {
  acceptFact,
  correctFact,
  type FactHistoryItem,
  type FactReviewItem,
  formatConfidence,
  getFactHistory,
  listReviewFacts,
  rejectFact,
} from "@/lib/phase6";

export default function ReviewPage() {
  const [facts, setFacts] = useState<FactReviewItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [statusFilter, setStatusFilter] = useState("needs_review");
  const [metricFilter, setMetricFilter] = useState("");

  // Correction Modal State
  const [correctingFact, setCorrectingFact] = useState<FactReviewItem | null>(null);
  const [corrValue, setCorrValue] = useState("");
  const [corrCurrency, setCorrCurrency] = useState("");
  const [corrScale, setCorrScale] = useState("");
  const [corrPeriod, setCorrPeriod] = useState("");
  const [corrReason, setCorrReason] = useState("");
  const [savingCorr, setSavingCorr] = useState(false);

  // Rejection Modal State
  const [rejectingFact, setRejectingFact] = useState<FactReviewItem | null>(null);
  const [rejReason, setRejReason] = useState("");
  const [savingRej, setSavingRej] = useState(false);

  // History Modal State
  const [historyFact, setHistoryFact] = useState<FactReviewItem | null>(null);
  const [historyItems, setHistoryItems] = useState<FactHistoryItem[] | null>(null);
  const [loadingHistory, setLoadingHistory] = useState(false);

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listReviewFacts({
        status: statusFilter || undefined,
        metric: metricFilter || undefined,
        limit: 100,
      });
      setFacts(res.items);
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load review items.");
    } finally {
      setLoading(false);
    }
  }, [statusFilter, metricFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const handleAccept = async (factId: string) => {
    try {
      await acceptFact(factId);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not accept fact.");
    }
  };

  const openCorrectModal = (fact: FactReviewItem) => {
    setCorrectingFact(fact);
    setCorrValue(fact.value);
    setCorrCurrency(fact.currency || "IDR");
    setCorrScale(fact.scale);
    setCorrPeriod(fact.period_label);
    setCorrReason("");
  };

  const handleCorrectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!correctingFact) return;
    try {
      setSavingCorr(true);
      await correctFact(correctingFact.id, {
        value: corrValue.trim(),
        currency: corrCurrency.trim() || undefined,
        scale: corrScale.trim() || undefined,
        period_label: corrPeriod.trim() || undefined,
        reason: corrReason.trim() || undefined,
      });
      setCorrectingFact(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not save correction.");
    } finally {
      setSavingCorr(false);
    }
  };

  const openRejectModal = (fact: FactReviewItem) => {
    setRejectingFact(fact);
    setRejReason("");
  };

  const handleRejectSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rejectingFact) return;
    try {
      setSavingRej(true);
      await rejectFact(rejectingFact.id, {
        reason: rejReason.trim() || undefined,
      });
      setRejectingFact(null);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not reject fact.");
    } finally {
      setSavingRej(false);
    }
  };

  const openHistoryModal = async (fact: FactReviewItem) => {
    setHistoryFact(fact);
    try {
      setLoadingHistory(true);
      const items = await getFactHistory(fact.id);
      setHistoryItems(items);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not load history.");
    } finally {
      setLoadingHistory(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Extraction Review Queue</h1>
          <p className="text-sm text-slate-500">
            Verify, accept, or correct extracted facts. Corrections preserve historical provenance.
          </p>
        </div>
        <div className="text-xs text-slate-500">
          Showing {facts?.length ?? 0} of {total} facts
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {/* Filters Toolbar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
        <div className="flex items-center gap-2">
          <label htmlFor="filter-status" className="font-medium text-slate-700">
            Status:
          </label>
          <select
            id="filter-status"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-slate-300 bg-surface px-2 py-1"
          >
            <option value="">All Statuses</option>
            <option value="needs_review">Needs Review</option>
            <option value="accepted">Accepted</option>
            <option value="corrected">Corrected</option>
            <option value="rejected">Rejected</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="filter-metric" className="font-medium text-slate-700">
            Metric:
          </label>
          <select
            id="filter-metric"
            value={metricFilter}
            onChange={(e) => setMetricFilter(e.target.value)}
            className="rounded border border-slate-300 bg-surface px-2 py-1"
          >
            <option value="">All Metrics</option>
            <option value="revenue">Revenue</option>
            <option value="net_income">Net Income</option>
            <option value="operating_income">Operating Income</option>
            <option value="gross_profit">Gross Profit</option>
            <option value="total_assets">Total Assets</option>
            <option value="total_liabilities">Total Liabilities</option>
            <option value="equity">Equity</option>
            <option value="cash">Cash</option>
            <option value="total_debt">Total Debt</option>
          </select>
        </div>
      </div>

      {/* Facts Review Table */}
      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500">Loading extraction queue...</div>
      ) : facts && facts.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Metric & Period</th>
                <th className="px-4 py-3 text-right">Extracted Value</th>
                <th className="px-4 py-3">Confidence</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Source Evidence</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {facts.map((fact) => {
                const conf = formatConfidence(fact.confidence);
                return (
                  <tr key={fact.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{fact.metric_name}</div>
                      <div className="text-xs text-slate-500">{fact.period_label}</div>
                    </td>
                    <td className="px-4 py-3 text-right font-medium">
                      <div>{formatAmount(fact.value, fact.currency)}</div>
                      <div className="text-xs text-slate-400">
                        {fact.original_text} ({fact.scale})
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          conf.label === "High"
                            ? "bg-emerald-50 text-emerald-700"
                            : conf.label === "Medium"
                              ? "bg-blue-50 text-blue-700"
                              : "bg-amber-50 text-amber-700"
                        }`}
                      >
                        {conf.label} ({Math.round(Number.parseFloat(fact.confidence) * 100)}%)
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`rounded px-2 py-0.5 text-xs font-medium ${
                          fact.status === "accepted"
                            ? "bg-emerald-50 text-emerald-700"
                            : fact.status === "corrected"
                              ? "bg-blue-50 text-blue-700"
                              : fact.status === "rejected"
                                ? "bg-rose-50 text-rose-700"
                                : "bg-amber-50 text-amber-700"
                        }`}
                      >
                        {fact.status === "accepted"
                          ? "✓ Accepted"
                          : fact.status === "corrected"
                            ? "✎ Corrected"
                            : fact.status === "rejected"
                              ? "✕ Rejected"
                              : "? Needs Review"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-600">
                      {fact.evidence ? (
                        <div>
                          <div>Page {fact.evidence.page_number}</div>
                          {fact.evidence.section_title && (
                            <div className="truncate max-w-xs text-slate-400">
                              {fact.evidence.section_title}
                            </div>
                          )}
                        </div>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-1.5">
                        {fact.status !== "accepted" && (
                          <button
                            type="button"
                            onClick={() => handleAccept(fact.id)}
                            className="rounded bg-emerald-600 px-2 py-1 text-xs font-medium text-white hover:bg-emerald-700 dark:hover:bg-emerald-500"
                            title="Accept fact as authoritative"
                          >
                            Accept
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openCorrectModal(fact)}
                          className="rounded border border-slate-200 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                          title="Manually correct extracted value"
                        >
                          Correct
                        </button>
                        {fact.status !== "rejected" && (
                          <button
                            type="button"
                            onClick={() => openRejectModal(fact)}
                            className="rounded border border-rose-200 px-2 py-1 text-xs font-medium text-rose-600 hover:bg-rose-50"
                            title="Reject extracted fact"
                          >
                            Reject
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => openHistoryModal(fact)}
                          className="rounded border border-slate-200 px-2 py-1 text-xs text-slate-500 hover:bg-slate-100"
                          title="View revision history"
                        >
                          History
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 py-12 text-center text-sm text-slate-500">
          No financial facts match your current review filters.
        </div>
      )}

      {/* Correction Modal */}
      {correctingFact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
          <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-surface p-6 shadow-xl">
            <h2 className="text-base font-semibold text-slate-900">
              Correct Financial Fact: {correctingFact.metric_name}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Modifying an extracted fact updates the canonical value and permanently logs the audit
              trail with your stated reason.
            </p>

            <form onSubmit={handleCorrectSubmit} className="mt-4 space-y-3">
              <div>
                <label htmlFor="corr-val" className="block text-xs font-medium text-slate-700">
                  Value (Exact Decimal) *
                </label>
                <input
                  id="corr-val"
                  type="text"
                  required
                  value={corrValue}
                  onChange={(e) => setCorrValue(e.target.value)}
                  className="mt-1 w-full rounded border border-slate-300 px-3 py-1.5 font-mono text-sm"
                />
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label htmlFor="corr-curr" className="block text-xs font-medium text-slate-700">
                    Currency
                  </label>
                  <input
                    id="corr-curr"
                    type="text"
                    value={corrCurrency}
                    onChange={(e) => setCorrCurrency(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-300 px-2.5 py-1.5 text-sm"
                  />
                </div>
                <div>
                  <label htmlFor="corr-scale" className="block text-xs font-medium text-slate-700">
                    Scale
                  </label>
                  <select
                    id="corr-scale"
                    value={corrScale}
                    onChange={(e) => setCorrScale(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
                  >
                    <option value="units">Units</option>
                    <option value="thousands">Thousands</option>
                    <option value="millions">Millions</option>
                    <option value="billions">Billions</option>
                    <option value="trillions">Trillions</option>
                  </select>
                </div>
                <div>
                  <label htmlFor="corr-period" className="block text-xs font-medium text-slate-700">
                    Period Label
                  </label>
                  <input
                    id="corr-period"
                    type="text"
                    value={corrPeriod}
                    onChange={(e) => setCorrPeriod(e.target.value)}
                    className="mt-1 w-full rounded border border-slate-300 px-2.5 py-1.5 text-sm"
                  />
                </div>
              </div>

              <div>
                <label htmlFor="corr-reason" className="block text-xs font-medium text-slate-700">
                  Reason for Correction *
                </label>
                <textarea
                  id="corr-reason"
                  required
                  rows={2}
                  value={corrReason}
                  onChange={(e) => setCorrReason(e.target.value)}
                  placeholder="e.g. Verified against page 87 audited note table."
                  className="mt-1 w-full rounded border border-slate-300 p-2 text-xs"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setCorrectingFact(null)}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingCorr || !corrValue.trim() || !corrReason.trim()}
                  className="rounded bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover disabled:opacity-50"
                >
                  {savingCorr ? "Saving..." : "Save Correction"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {rejectingFact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
          <div className="w-full max-w-md rounded-lg border border-slate-200 bg-surface p-6 shadow-xl">
            <h2 className="text-base font-semibold text-slate-900">
              Reject Fact: {rejectingFact.metric_name}
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Rejected facts will be excluded from financial calculations and balance sheet
              reconciliation.
            </p>
            <form onSubmit={handleRejectSubmit} className="mt-4 space-y-3">
              <div>
                <label htmlFor="rej-reason" className="block text-xs font-medium text-slate-700">
                  Rejection Reason (Optional)
                </label>
                <textarea
                  id="rej-reason"
                  rows={2}
                  value={rejReason}
                  onChange={(e) => setRejReason(e.target.value)}
                  placeholder="e.g. Number corresponds to subsidiary, not consolidated."
                  className="mt-1 w-full rounded border border-slate-300 p-2 text-xs"
                />
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setRejectingFact(null)}
                  className="rounded border border-slate-300 px-3 py-1.5 text-xs hover:bg-slate-100"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={savingRej}
                  className="rounded bg-rose-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-rose-700 dark:hover:bg-rose-500 disabled:opacity-50"
                >
                  {savingRej ? "Rejecting..." : "Confirm Reject"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* History Drawer Modal */}
      {historyFact && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/50 p-4">
          <div className="w-full max-w-lg rounded-lg border border-slate-200 bg-surface p-6 shadow-xl">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-900">
                Revision History: {historyFact.metric_name}
              </h2>
              <button
                type="button"
                onClick={() => setHistoryFact(null)}
                className="text-xs text-slate-400 hover:text-slate-700"
              >
                ✕ Close
              </button>
            </div>
            <p className="mt-1 text-xs text-slate-500">
              Original extracted value: {historyFact.original_text} ({historyFact.scale})
            </p>

            <div className="mt-4 max-h-80 overflow-y-auto space-y-3">
              {loadingHistory ? (
                <div className="py-6 text-center text-xs text-slate-400">Loading history...</div>
              ) : historyItems && historyItems.length > 0 ? (
                historyItems.map((h) => (
                  <div
                    key={h.id}
                    className="rounded border border-slate-200 bg-slate-50 p-3 text-xs"
                  >
                    <div className="flex items-center justify-between">
                      <span className="font-semibold uppercase tracking-wider text-slate-700">
                        {h.action}
                      </span>
                      <span className="text-slate-400">
                        {new Date(h.created_at).toLocaleString()}
                      </span>
                    </div>
                    {h.original_value && h.new_value && (
                      <div className="mt-1 font-mono text-[11px] text-slate-600">
                        <span className="line-through text-rose-600">{h.original_value}</span> →{" "}
                        <span className="text-emerald-700 font-semibold">{h.new_value}</span>
                      </div>
                    )}
                    {h.reason && (
                      <div className="mt-1 text-slate-700">
                        <strong>Reason:</strong> {h.reason}
                      </div>
                    )}
                  </div>
                ))
              ) : (
                <div className="py-6 text-center text-xs text-slate-400">
                  No previous corrections recorded for this fact.
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
