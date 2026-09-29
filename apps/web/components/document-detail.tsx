"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { CalculationsPanel } from "@/components/calculations-panel";
import { Dashboard } from "@/components/dashboard";
import { ExportPanel } from "@/components/export-panel";
import { EvidenceCard, FactsPanel } from "@/components/facts-panel";
import { ShowEvidence } from "@/components/financial-values";
import { PageViewer } from "@/components/page-viewer";
import { ReconciliationView } from "@/components/reconciliation";
import { SourcePanel } from "@/components/source-panel";
import { ProcessingSteps, StatusBadge } from "@/components/status-badge";
import { Timeline } from "@/components/timeline";
import { ApiError, api } from "@/lib/api";
import {
  DOCUMENT_TYPE_LABEL,
  type FinancialFact,
  formatBytes,
  formatDate,
  isSettled,
  type ProspectDocument,
} from "@/lib/documents";
import {
  evidenceKey,
  type Financials,
  latestPeriod,
  parseEvidenceKey,
  type Scope,
  TABS,
  type Tab,
} from "@/lib/financials";

const POLL_MS = 5000;
const USES_FINANCIALS: Tab[] = ["overview", "timeline", "reconciliation", "export"];

export type WorkspaceState = {
  tab: Tab;
  scope: Scope;
  period: string | null;
  page: number;
  evidence: string | null; // the fact open in the source panel (lib/financials evidenceKey)
};

export function DocumentDetail({ id, initial }: { id: string; initial: WorkspaceState }) {
  const [document, setDocument] = useState<ProspectDocument | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [opening, setOpening] = useState(false);
  const router = useRouter();
  const [state, setState] = useState(initial);
  const [evidence, setEvidence] = useState<FinancialFact | null>(null);
  const [fin, setFin] = useState<Financials | null>(null);
  const [finError, setFinError] = useState<string | null>(null);

  function href(patch: Partial<WorkspaceState>): string {
    const next = { ...state, ...patch };
    const params = new URLSearchParams({ tab: next.tab, scope: next.scope, page: `${next.page}` });
    if (next.period) params.set("period", next.period);
    if (next.evidence) params.set("evidence", next.evidence);
    return `?${params}`;
  }
  function update(patch: Partial<WorkspaceState>) {
    setState((s) => ({ ...s, ...patch }));
    router.replace(href(patch), { scroll: false }); // shareable link to this view
  }
  const goToPage = (page: number) => update({ page });

  // The source opens beside the numbers; only the Evidence tab's own viewer follows the page.
  function showEvidence(fact: FinancialFact) {
    setEvidence(fact);
    const page = state.tab === "evidence" ? { page: fact.evidence.page_number } : {};
    update({ evidence: evidenceKey(fact), ...page });
  }
  function closeEvidence() {
    setEvidence(null);
    update({ evidence: null });
  }

  const load = useCallback(async () => {
    try {
      setDocument(await api<ProspectDocument>(`/documents/${id}`));
      setError(null);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, "unknown", "Could not load document."));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  const ready = document?.status === "READY";
  const scope: Scope = document?.company_name ? state.scope : "document";
  const loadFinancials = useCallback(async () => {
    setFinError(null);
    try {
      setFin(await api<Financials>(`/documents/${id}/financials?scope=${scope}`));
    } catch (e) {
      setFinError(e instanceof ApiError ? e.message : "Could not load financial data.");
    }
  }, [id, scope]);
  useEffect(() => {
    if (ready) loadFinancials();
  }, [ready, loadFinancials]);

  // A shared link with ?evidence= reopens that fact's source once the document is ready. A fact
  // that is gone (or not this session's) simply leaves the panel closed.
  const restoring = useRef(initial.evidence);
  useEffect(() => {
    const key = parseEvidenceKey(restoring.current);
    if (!ready) return;
    restoring.current = null;
    if (!key) return;
    api<{ fact: FinancialFact }>(`/documents/${key.documentId}/evidence/${key.evidenceId}`)
      .then((view) => setEvidence(view.fact))
      .catch(() => setState((s) => ({ ...s, evidence: null })));
  }, [ready]);

  const active = document ? !isSettled(document.status) : false;
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(load, POLL_MS);
    return () => clearInterval(timer);
  }, [active, load]);

  async function openPdf() {
    setOpening(true);
    try {
      const { url } = await api<{ url: string }>(`/documents/${id}/download-url`);
      // A signed storage URL: http(s) only (never javascript: or data:), opened without an
      // opener or a referrer.
      if (!["https:", "http:"].includes(new URL(url).protocol)) {
        throw new ApiError(0, "invalid_url", "The file link is not valid.");
      }
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      setError(e instanceof ApiError ? e : null);
    } finally {
      setOpening(false);
    }
  }

  const back = (
    <Link href="/" className="text-sm text-slate-600 hover:text-slate-900">
      ← Documents
    </Link>
  );

  if (error?.status === 404) {
    return (
      <div className="space-y-3">
        {back}
        <h1 className="text-xl font-semibold">Not found</h1>
        <p className="text-sm text-slate-600">This document does not exist.</p>
      </div>
    );
  }
  if (!document) {
    return (
      <div className="space-y-3">
        {back}
        {error ? (
          <p role="alert" className="text-sm text-red-800">
            {error.message}{" "}
            <button type="button" onClick={load} className="underline">
              Try again
            </button>
          </p>
        ) : (
          <p role="status" className="text-sm text-slate-500">
            Loading…
          </p>
        )}
      </div>
    );
  }

  const fileAvailable = document.status !== "UPLOADING" && document.status !== "FAILED";
  const rows: [string, string][] = [
    ["Type", DOCUMENT_TYPE_LABEL[document.document_type]],
    ["Fiscal year", document.fiscal_year ? `FY${document.fiscal_year}` : "Not specified"],
    ["Company", document.company_name ?? "Not specified"],
    ["Size", formatBytes(document.size_bytes)],
    ["Format", document.mime_type],
    ["Uploaded", formatDate(document.created_at)],
    [
      "Deleted automatically",
      document.delete_after ? formatDate(document.delete_after) : "Not scheduled",
    ],
    ["Last updated", formatDate(document.updated_at)],
    ["Document ID", document.id],
  ];

  return (
    <div className="space-y-6">
      {back}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 space-y-2">
          <h1 className="break-words text-2xl font-semibold tracking-tight">{document.filename}</h1>
          <StatusBadge status={document.status} />
          {ready && (
            <nav aria-label="Research tools" className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
              {[
                [`/data-quality?document_id=${document.id}`, "Data quality"],
                ["/review", "Review figures"],
                ["/scenarios", "Scenarios"],
                ["/diff", "Compare reports"],
              ].map(([href, label]) => (
                <Link
                  key={label}
                  href={href}
                  className="text-slate-600 underline hover:text-slate-900"
                >
                  {label}
                </Link>
              ))}
            </nav>
          )}
        </div>
        {fileAvailable && (
          <button
            type="button"
            onClick={openPdf}
            disabled={opening}
            className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50 disabled:opacity-50"
          >
            {opening ? "Opening…" : "Open PDF"}
          </button>
        )}
      </div>

      {document.status === "FAILED" && (
        <div
          role="alert"
          className="rounded border border-red-200 bg-red-50 p-4 text-sm text-red-900"
        >
          <p className="font-medium">Processing failed</p>
          <p className="mt-1">{document.processing_error ?? "No error details were recorded."}</p>
          <p className="mt-2">
            <Link href="/" className="underline">
              Upload a different file
            </Link>
          </p>
        </div>
      )}
      {error && error.status !== 404 && (
        <p role="alert" className="text-sm text-red-800">
          {error.message}
        </p>
      )}

      <dl className="grid max-w-2xl grid-cols-[10rem_1fr] gap-x-4 gap-y-2 text-sm">
        {rows.map(([label, value]) => (
          <div key={label} className="contents">
            <dt className="text-slate-500">{label}</dt>
            <dd className="break-all">{value}</dd>
          </div>
        ))}
      </dl>

      {ready ? (
        <Workspace
          document={document}
          state={{ ...state, scope }}
          href={href}
          update={update}
          fin={fin?.scope === scope ? fin : null}
          finError={finError}
          reload={loadFinancials}
          evidence={evidence}
          closeEvidence={closeEvidence}
          showEvidence={showEvidence}
          goToPage={goToPage}
          onCompanyChange={(d) => {
            setDocument(d);
            setFin(null);
          }}
        />
      ) : (
        document.status !== "FAILED" && (
          <div className="space-y-2">
            <ProcessingSteps status={document.status} />
            <p className="text-sm text-slate-500">
              Long reports can take a couple of minutes. This page updates by itself.
            </p>
          </div>
        )
      )}
    </div>
  );
}

function CompanyEditor({
  document,
  onSaved,
}: {
  document: ProspectDocument;
  onSaved: (d: ProspectDocument) => void;
}) {
  const [value, setValue] = useState(document.company_name ?? "");
  const [message, setMessage] = useState<string | null>(null);
  async function save(e: React.FormEvent) {
    e.preventDefault();
    try {
      const saved = await api<ProspectDocument>(`/documents/${document.id}`, {
        method: "PATCH",
        body: JSON.stringify({ company_name: value.trim() || null }),
      });
      onSaved(saved);
      setMessage("Saved.");
    } catch (err) {
      setMessage(err instanceof ApiError ? err.message : "Could not save.");
    }
  }
  return (
    <form onSubmit={save} className="flex flex-wrap items-center gap-2 text-sm">
      <label htmlFor="company" className="text-slate-600">
        Company
      </label>
      <input
        id="company"
        value={value}
        maxLength={200}
        onChange={(e) => setValue(e.target.value)}
        placeholder="e.g. PT Contoh Sejahtera Tbk"
        className="w-64 rounded border border-slate-300 px-2 py-1"
      />
      <button type="submit" className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-50">
        Save
      </button>
      <span role="status" className="text-slate-500">
        {message}
      </span>
      <span className="w-full text-xs text-slate-500">
        Reports with the same company name are combined in the company timeline.
      </span>
    </form>
  );
}

function Workspace(props: {
  document: ProspectDocument;
  state: WorkspaceState;
  href: (patch: Partial<WorkspaceState>) => string;
  update: (patch: Partial<WorkspaceState>) => void;
  fin: Financials | null;
  finError: string | null;
  reload: () => void;
  evidence: FinancialFact | null;
  closeEvidence: () => void;
  showEvidence: (f: FinancialFact) => void;
  goToPage: (page: number) => void;
  onCompanyChange: (d: ProspectDocument) => void;
}) {
  const { document, state, href, update, fin, finError, evidence } = props;
  const { tab, scope, page } = state;
  const period = fin && state.period && fin.periods.includes(state.period) ? state.period : null;
  const shownPeriod = period ?? (fin ? latestPeriod(fin) : null);
  const panelOpen = evidence !== null && tab !== "evidence"; // the Evidence tab shows it inline

  function financialsBody() {
    if (finError) {
      return (
        <p role="alert" className="text-sm text-red-800">
          {finError}{" "}
          <button type="button" onClick={props.reload} className="underline">
            Try again
          </button>
        </p>
      );
    }
    if (!fin) {
      return (
        <p role="status" className="text-sm text-slate-500">
          Loading financial data…
        </p>
      );
    }
    if (fin.cells.length === 0 && tab !== "export") {
      return (
        <p className="rounded border border-dashed border-slate-300 px-4 py-6 text-sm text-slate-600">
          No annual or balance-sheet financial facts were found with enough evidence in this{" "}
          {scope === "company" ? "company" : "document"}. Prospect does not guess values.
        </p>
      );
    }
    if (tab === "overview" && shownPeriod) {
      return (
        <Dashboard
          fin={fin}
          documentId={document.id}
          scope={scope}
          period={shownPeriod}
          onPeriod={(p) => update({ period: p })}
        />
      );
    }
    if (tab === "timeline") return <Timeline fin={fin} documentId={document.id} scope={scope} />;
    if (tab === "reconciliation") return <ReconciliationView fin={fin} />;
    return <ExportPanel fin={fin} documentId={document.id} scope={scope} />;
  }

  return (
    <div className="space-y-6">
      <CompanyEditor document={document} onSaved={props.onCompanyChange} />
      <nav aria-label="Document workspace" className="border-b border-slate-200">
        <ul className="-mb-px flex flex-wrap gap-x-1">
          {TABS.map(([key, label]) => (
            <li key={key}>
              <Link
                href={href({ tab: key })}
                replace
                scroll={false}
                onClick={(e) => {
                  e.preventDefault();
                  update({ tab: key });
                }}
                aria-current={tab === key ? "page" : undefined}
                className={`inline-block border-b-2 px-3 py-2 text-sm ${
                  tab === key
                    ? "border-slate-900 font-medium text-slate-900"
                    : "border-transparent text-slate-600 hover:text-slate-900"
                }`}
              >
                {label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      <ShowEvidence.Provider value={props.showEvidence}>
        <div
          className={
            panelOpen ? "grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_28rem]" : undefined
          }
        >
          <div className="min-w-0 space-y-6">
            {USES_FINANCIALS.includes(tab) && document.company_name && (
              <fieldset className="flex flex-wrap items-center gap-4 text-sm">
                <legend className="sr-only">Scope</legend>
                {(["document", "company"] as const).map((s) => (
                  <label key={s} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="scope"
                      checked={scope === s}
                      onChange={() => update({ scope: s })}
                    />
                    {s === "document" ? "This document" : `All reports of ${document.company_name}`}
                  </label>
                ))}
              </fieldset>
            )}

            {USES_FINANCIALS.includes(tab) && financialsBody()}
            {tab === "financials" && (
              <div className="space-y-8">
                <FactsPanel documentId={document.id} onShowEvidence={props.showEvidence} />
                <CalculationsPanel documentId={document.id} onShowEvidence={props.showEvidence} />
              </div>
            )}
            {tab === "evidence" && (
              <div className="space-y-3">
                {evidence ? (
                  <EvidenceCard fact={evidence} onClose={props.closeEvidence} />
                ) : (
                  <p className="text-xs text-slate-500">
                    Browse the extracted pages. Choose a fact under Financials, Overview or Timeline
                    to see its source here or in the evidence explorer.
                  </p>
                )}
                <PageViewer
                  documentId={document.id}
                  page={page}
                  onPageChange={props.goToPage}
                  highlight={
                    evidence?.evidence.page_number === page ? evidence.evidence.content : null
                  }
                />
              </div>
            )}
          </div>
          {panelOpen && evidence && <SourcePanel fact={evidence} onClose={props.closeEvidence} />}
        </div>
      </ShowEvidence.Provider>
    </div>
  );
}
