"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api";
import { type AuditEvent, listAuditEvents } from "@/lib/phase6";

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [eventTypeFilter, setEventTypeFilter] = useState("");
  const [entityTypeFilter, setEntityTypeFilter] = useState("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listAuditEvents({
        event_type: eventTypeFilter || undefined,
        entity_type: entityTypeFilter || undefined,
        limit: 100,
      });
      setEvents(res.items);
      setTotal(res.total);
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Failed to load audit trail.");
    } finally {
      setLoading(false);
    }
  }, [eventTypeFilter, entityTypeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Audit Trail</h1>
          <p className="text-sm text-slate-500">
            Append-only, immutable activity log tracking all facts, reviews, anomaly lifecycle, and
            workspace changes.
          </p>
        </div>
        <div className="text-xs text-slate-500">Total Recorded Events: {total}</div>
      </div>

      {error && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-800"
        >
          {error}
        </div>
      )}

      {/* Filter toolbar */}
      <div className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
        <div className="flex items-center gap-2">
          <label htmlFor="filter-event-type" className="font-medium text-slate-700">
            Event Type:
          </label>
          <select
            id="filter-event-type"
            value={eventTypeFilter}
            onChange={(e) => setEventTypeFilter(e.target.value)}
            className="rounded border border-slate-300 bg-surface px-2 py-1"
          >
            <option value="">All Events</option>
            <option value="FACT_ACCEPTED">FACT_ACCEPTED</option>
            <option value="FACT_CORRECTED">FACT_CORRECTED</option>
            <option value="FACT_REJECTED">FACT_REJECTED</option>
            <option value="ANOMALY_ACKNOWLEDGED">ANOMALY_ACKNOWLEDGED</option>
            <option value="ANOMALY_RESOLVED">ANOMALY_RESOLVED</option>
            <option value="SCENARIO_CREATED">SCENARIO_CREATED</option>
            <option value="SCENARIO_UPDATED">SCENARIO_UPDATED</option>
            <option value="SCENARIO_DELETED">SCENARIO_DELETED</option>
            <option value="COMPANY_CREATED">COMPANY_CREATED</option>
            <option value="WATCHLIST_ADDED">WATCHLIST_ADDED</option>
            <option value="DOCUMENT_UPLOADED">DOCUMENT_UPLOADED</option>
            <option value="DOCUMENT_PROCESSED">DOCUMENT_PROCESSED</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <label htmlFor="filter-entity-type" className="font-medium text-slate-700">
            Entity Type:
          </label>
          <select
            id="filter-entity-type"
            value={entityTypeFilter}
            onChange={(e) => setEntityTypeFilter(e.target.value)}
            className="rounded border border-slate-300 bg-surface px-2 py-1"
          >
            <option value="">All Entities</option>
            <option value="financial_fact">financial_fact</option>
            <option value="data_quality_issue">data_quality_issue</option>
            <option value="scenario">scenario</option>
            <option value="company">company</option>
            <option value="watchlist_entry">watchlist_entry</option>
            <option value="document">document</option>
          </select>
        </div>
      </div>

      {/* Events List */}
      {loading ? (
        <div className="py-12 text-center text-sm text-slate-500">Loading audit trail...</div>
      ) : events && events.length > 0 ? (
        <div className="space-y-3">
          {events.map((evt) => (
            <div
              key={evt.id}
              className="rounded-lg border border-slate-200 bg-surface p-4 shadow-2xs hover:border-slate-300"
            >
              <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 pb-2">
                <div className="flex items-center gap-2">
                  <span className="rounded bg-slate-900 px-2 py-0.5 font-mono text-[11px] font-semibold text-white dark:text-slate-950">
                    {evt.event_type}
                  </span>
                  <span className="text-xs text-slate-500">
                    Entity: <span className="font-mono text-slate-700">{evt.entity_type}</span> (ID:{" "}
                    <span className="font-mono text-slate-500">{evt.entity_id.slice(0, 8)}...</span>
                    )
                  </span>
                </div>
                <div className="text-xs text-slate-400">
                  {new Date(evt.timestamp).toLocaleString()}
                </div>
              </div>

              {evt.reason && (
                <div className="mt-2 text-xs text-slate-700">
                  <strong className="font-medium">Reason:</strong> {evt.reason}
                </div>
              )}

              {/* Before vs After State */}
              {(evt.before_state || evt.after_state) && (
                <div className="mt-3 grid grid-cols-1 sm:grid-cols-2 gap-3 text-[11px]">
                  {evt.before_state && (
                    <div className="rounded border border-rose-100 bg-rose-50/40 p-2.5">
                      <div className="font-semibold text-rose-800 uppercase tracking-wider text-[10px]">
                        State Before
                      </div>
                      <pre className="mt-1 overflow-x-auto font-mono text-slate-700">
                        {JSON.stringify(evt.before_state, null, 2)}
                      </pre>
                    </div>
                  )}
                  {evt.after_state && (
                    <div className="rounded border border-emerald-100 bg-emerald-50/40 p-2.5">
                      <div className="font-semibold text-emerald-800 uppercase tracking-wider text-[10px]">
                        State After
                      </div>
                      <pre className="mt-1 overflow-x-auto font-mono text-slate-700">
                        {JSON.stringify(evt.after_state, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-slate-300 py-12 text-center text-sm text-slate-500">
          No audit events recorded yet. Actions such as correcting facts, updating anomalies, and
          saving scenarios will be logged here.
        </div>
      )}
    </div>
  );
}
