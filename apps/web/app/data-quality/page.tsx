"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import {
  type AnomalyStatus,
  anomalySeverityBadge,
  type DataQualityIssue,
  type DataQualitySummary,
  getDataQuality,
  updateDataQualityStatus,
} from "@/lib/phase6";

export default function DataQualityPage() {
  const searchParams = useSearchParams();
  const companyId = searchParams?.get("company_id") || undefined;
  const docId = searchParams?.get("document_id") || undefined;

  const [issues, setIssues] = useState<DataQualityIssue[] | null>(null);
  const [summary, setSummary] = useState<DataQualitySummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [severityFilter, setSeverityFilter] = useState<string>("");
  const [statusFilter, setStatusFilter] = useState<string>("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await getDataQuality({
        company_id: companyId,
        document_id: docId,
        severity: severityFilter || undefined,
        status: statusFilter || undefined,
        run_fresh: true,
      });
      setIssues(res.items);
      setSummary(res.summary);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load data quality checks.");
    } finally {
      setLoading(false);
    }
  }, [companyId, docId, severityFilter, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const handleUpdateStatus = async (issueId: string, newStatus: AnomalyStatus) => {
    try {
      await updateDataQualityStatus(issueId, newStatus);
      await load();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Could not update issue status.");
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            Data Quality & Anomaly Detection
          </h1>
          <p className="text-sm text-slate-500">
            Deterministic rule-based checks for missing data, conflicts, unit mismatches, large
            swings, and accounting consistency.
          </p>
        </div>
        <button
          type="button"
          onClick={load}
          className="rounded border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
        >
          ⟳ Re-run Quality Checks
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

      {/* KPI Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-4">
            <div className="text-xs uppercase text-slate-500">Total Anomalies</div>
            <div className="mt-1 text-2xl font-semibold tracking-tight">{summary.total}</div>
            <div className="mt-1 text-xs text-slate-400">Total detected issues</div>
          </div>
          <div className="rounded-lg border border-red-200 bg-red-50/40 p-4">
            <div className="flex items-center gap-1.5 text-xs font-medium uppercase text-red-800">
              <span>✕</span> Errors
            </div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-red-700">
              {summary.by_severity.error || 0}
            </div>
            <div className="mt-1 text-xs text-red-600/70">Requires prompt correction</div>
          </div>
          <div className="rounded-lg border border-amber-200 bg-amber-50/40 p-4">
            <div className="flex items-center gap-1.5 text-xs font-medium uppercase text-amber-800">
              <span>⚠</span> Warnings
            </div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-amber-700">
              {summary.by_severity.warning || 0}
            </div>
            <div className="mt-1 text-xs text-amber-600/70">Potential inconsistencies</div>
          </div>
          <div className="rounded-lg border border-blue-200 bg-blue-50/40 p-4">
            <div className="flex items-center gap-1.5 text-xs font-medium uppercase text-blue-800">
              <span>ℹ</span> Informational
            </div>
            <div className="mt-1 text-2xl font-semibold tracking-tight text-blue-700">
              {summary.by_severity.info || 0}
            </div>
            <div className="mt-1 text-xs text-blue-600/70">Data quality notices</div>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
        <div className="flex items-center gap-2">
          <label htmlFor="filter-sev" className="font-medium text-slate-700">
            Severity:
          </label>
          <select
            id="filter-sev"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1"
          >
            <option value="">All Severities</option>
            <option value="error">Error (✕)</option>
            <option value="warning">Warning (⚠)</option>
            <option value="info">Info (ℹ)</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="filter-st" className="font-medium text-slate-700">
            Status:
          </label>
          <select
            id="filter-st"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded border border-slate-300 bg-white px-2 py-1"
          >
            <option value="">All Statuses</option>
            <option value="open">Open</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
            <option value="ignored">Ignored</option>
          </select>
        </div>
      </div>

      {/* Anomalies Table */}
      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500">
          Running data quality checks...
        </div>
      ) : issues && issues.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-slate-200">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs font-medium uppercase text-slate-500">
              <tr>
                <th className="px-4 py-3">Severity</th>
                <th className="px-4 py-3">Rule & Metric</th>
                <th className="px-4 py-3">Period</th>
                <th className="px-4 py-3">Description</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200">
              {issues.map((issue) => {
                const badge = anomalySeverityBadge(issue.severity);
                return (
                  <tr key={issue.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-medium ${badge.className}`}
                      >
                        <span>{badge.symbol}</span>
                        <span>{badge.label}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <div className="font-medium text-slate-900">{issue.rule_code}</div>
                      <div className="text-xs text-slate-500">{issue.metric || "General"}</div>
                    </td>
                    <td className="px-4 py-3 text-slate-600">{issue.period_label || "—"}</td>
                    <td className="px-4 py-3 text-xs text-slate-700 max-w-md">
                      {issue.description}
                    </td>
                    <td className="px-4 py-3">
                      <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-medium uppercase text-slate-600">
                        {issue.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex justify-end gap-1.5 text-xs">
                        {issue.status === "open" && (
                          <button
                            type="button"
                            onClick={() => handleUpdateStatus(issue.id, "acknowledged")}
                            className="rounded border border-slate-200 px-2 py-1 text-slate-700 hover:bg-slate-100"
                          >
                            Acknowledge
                          </button>
                        )}
                        {issue.status !== "resolved" && (
                          <button
                            type="button"
                            onClick={() => handleUpdateStatus(issue.id, "resolved")}
                            className="rounded bg-emerald-600 px-2 py-1 text-white hover:bg-emerald-700"
                          >
                            Resolve
                          </button>
                        )}
                        {issue.status !== "ignored" && issue.status !== "resolved" && (
                          <button
                            type="button"
                            onClick={() => handleUpdateStatus(issue.id, "ignored")}
                            className="rounded border border-slate-200 px-2 py-1 text-slate-500 hover:bg-slate-100"
                          >
                            Ignore
                          </button>
                        )}
                        {issue.document_id && (
                          <Link
                            href={`/documents/${issue.document_id}`}
                            className="rounded border border-slate-200 px-2 py-1 text-slate-700 hover:bg-slate-100"
                          >
                            View Filing →
                          </Link>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-emerald-200 bg-emerald-50/20 py-12 text-center text-sm text-emerald-800">
          ✓ All financial data quality checks passed with zero open issues!
        </div>
      )}
    </div>
  );
}
