import { api } from "./api.ts";
import type { FinancialFact, ProspectDocument } from "./documents.ts";
import type { Financials } from "./financials.ts";

// ==========================================
// 1. Document Diff Types & API
// ==========================================

export type DiffMetadata = {
  fiscal_year_match: boolean;
  company_name_match: boolean;
  doc_type_match: boolean;
  notes: string[];
};

export type FinancialFactDiffItem = {
  metric: string;
  metric_name: string;
  val_a: string | null;
  val_b: string | null;
  change_pct: string | null;
  currency: string | null;
  evidence_a: FinancialFact["evidence"] | null;
  evidence_b: FinancialFact["evidence"] | null;
};

export type SectionDiffStatus = "added" | "removed" | "changed" | "unchanged";

export type SectionDiffItem = {
  section_title: string;
  status: SectionDiffStatus;
  page_a: number | null;
  page_b: number | null;
  char_diff: number;
  uncertain: boolean;
};

export type TextDiffSection = {
  section_title: string;
  status: SectionDiffStatus;
  unified_diff: string[];
};

export type DocumentDiffResponse = {
  doc_a: { id: string; filename: string; fiscal_year: number | null; company_name: string | null };
  doc_b: { id: string; filename: string; fiscal_year: number | null; company_name: string | null };
  metadata_diff: DiffMetadata;
  financial_diff: FinancialFactDiffItem[];
  section_diff: SectionDiffItem[];
  text_diff: TextDiffSection[];
};

export async function compareDocuments(
  docAId: string,
  docBId: string,
): Promise<DocumentDiffResponse> {
  return api<DocumentDiffResponse>("/documents/diff", {
    method: "POST",
    body: JSON.stringify({ doc_a_id: docAId, doc_b_id: docBId }),
  });
}

// ==========================================
// 2. Extraction Review Types & API
// ==========================================

export type FactReviewItem = FinancialFact;

export type FactCorrectionRequest = {
  value?: string;
  currency?: string;
  scale?: string;
  period_label?: string;
  metric?: string;
  reason?: string;
};

export type FactRejectionRequest = {
  reason?: string;
};

export type FactHistoryItem = {
  id: string;
  fact_id: string;
  action: "accepted" | "corrected" | "rejected";
  original_value: string | null;
  new_value: string | null;
  reason: string | null;
  actor_id: string | null;
  created_at: string;
};

export async function listReviewFacts(
  filters: Record<string, string | number | undefined> = {},
): Promise<{ items: FactReviewItem[]; total: number }> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(filters)) {
    if (v !== undefined && v !== "") query.set(k, String(v));
  }
  const qStr = query.toString();
  return api<{ items: FactReviewItem[]; total: number }>(
    `/financial-facts/review${qStr ? `?${qStr}` : ""}`,
  );
}

export async function acceptFact(factId: string): Promise<FactReviewItem> {
  return api<FactReviewItem>(`/financial-facts/${factId}/accept`, {
    method: "POST",
  });
}

export async function correctFact(
  factId: string,
  req: FactCorrectionRequest,
): Promise<FactReviewItem> {
  return api<FactReviewItem>(`/financial-facts/${factId}/correct`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function rejectFact(
  factId: string,
  req: FactRejectionRequest = {},
): Promise<FactReviewItem> {
  return api<FactReviewItem>(`/financial-facts/${factId}/reject`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function getFactHistory(factId: string): Promise<FactHistoryItem[]> {
  return api<FactHistoryItem[]>(`/financial-facts/${factId}/history`);
}

// ==========================================
// 3. Data Quality Types & API
// ==========================================

export type AnomalySeverity = "info" | "warning" | "error";
export type AnomalyStatus = "open" | "acknowledged" | "resolved" | "ignored";

export type DataQualityIssue = {
  id: string;
  user_id: string;
  document_id: string | null;
  company_id: string | null;
  rule_code: string;
  severity: AnomalySeverity;
  status: AnomalyStatus;
  metric: string | null;
  period_label: string | null;
  description: string;
  evidence_id: string | null;
  details: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type DataQualitySummary = {
  total: number;
  by_severity: Record<AnomalySeverity, number>;
  by_status: Record<AnomalyStatus, number>;
};

export type DataQualityResponse = {
  items: DataQualityIssue[];
  summary: DataQualitySummary;
};

export async function getDataQuality(
  params: Record<string, string | boolean | undefined> = {},
): Promise<DataQualityResponse> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) query.set(k, String(v));
  }
  const qStr = query.toString();
  return api<DataQualityResponse>(`/data-quality${qStr ? `?${qStr}` : ""}`);
}

export async function updateDataQualityStatus(
  issueId: string,
  status: AnomalyStatus,
): Promise<DataQualityIssue> {
  return api<DataQualityIssue>(`/data-quality/${issueId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

// ==========================================
// 4. Scenario Analysis Types & API
// ==========================================

export type ScenarioCalculationRequest = {
  base_revenue: string;
  base_net_income?: string | null;
  revenue_growth_pct?: string;
  net_margin_pct?: string | null;
};

export type ScenarioCalculationResult = {
  base_revenue: string;
  base_net_income: string | null;
  base_margin_pct: string | null;
  revenue_growth_pct: string;
  net_margin_pct: string | null;
  scenario_revenue: string;
  scenario_net_income: string | null;
  revenue_change: string;
  net_income_change: string | null;
  disclaimer: string;
};

export type Scenario = {
  id: string;
  user_id: string;
  company_id: string | null;
  document_id: string | null;
  name: string;
  description: string | null;
  base_period: string;
  base_revenue: string;
  base_net_income: string | null;
  base_margin_pct: string | null;
  revenue_growth_pct: string;
  net_margin_pct: string | null;
  scenario_revenue: string;
  scenario_net_income: string | null;
  revenue_change: string;
  net_income_change: string | null;
  assumptions: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export async function calculateScenarioPreview(
  req: ScenarioCalculationRequest,
): Promise<ScenarioCalculationResult> {
  return api<ScenarioCalculationResult>("/scenarios/calculate", {
    method: "POST",
    body: JSON.stringify(req),
  });
}

export async function listScenarios(
  params: Record<string, string | undefined> = {},
): Promise<Scenario[]> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v) query.set(k, v);
  }
  const qStr = query.toString();
  return api<Scenario[]>(`/scenarios${qStr ? `?${qStr}` : ""}`);
}

export async function createScenario(
  data: Partial<Scenario> & { name: string; base_period: string; base_revenue: string },
): Promise<Scenario> {
  return api<Scenario>("/scenarios", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateScenario(id: string, data: Partial<Scenario>): Promise<Scenario> {
  return api<Scenario>(`/scenarios/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteScenario(id: string): Promise<void> {
  return api<void>(`/scenarios/${id}`, {
    method: "DELETE",
  });
}

// ==========================================
// 5. Company Workspace Types & API
// ==========================================

// CompanySummaryOut: GET /companies, POST /companies, PATCH /companies/{id}.
export type CompanySummary = {
  id: string;
  name: string;
  ticker: string | null;
  country: string | null;
  // Primary reporting currency (context only): each fact carries its own currency.
  reporting_currency: string | null;
  description: string | null;
  document_count: number;
  latest_period: string | null;
  is_in_watchlist: boolean;
  created_at: string;
  updated_at: string;
};

// CompanyDetailOut: GET /companies/{id}. Figures come from `financials` (with evidence).
export type CompanyDetail = Omit<CompanySummary, "document_count"> & {
  documents: ProspectDocument[];
  financials: Financials | null;
  scenario_count: number;
};

export type CompanyUpdate = {
  name?: string;
  ticker?: string | null;
  country?: string | null;
  reporting_currency?: string;
  description?: string | null;
};

export async function listCompanies(): Promise<CompanySummary[]> {
  return api<CompanySummary[]>("/companies");
}

export async function getCompany(id: string): Promise<CompanyDetail> {
  return api<CompanyDetail>(`/companies/${id}`);
}

export async function createCompany(data: {
  name: string;
  ticker?: string | null;
  country?: string | null;
  reporting_currency?: string;
  description?: string | null;
}): Promise<CompanySummary> {
  return api<CompanySummary>("/companies", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function updateCompany(id: string, data: CompanyUpdate): Promise<CompanySummary> {
  return api<CompanySummary>(`/companies/${id}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export async function deleteCompany(id: string): Promise<void> {
  return api<void>(`/companies/${id}`, {
    method: "DELETE",
  });
}

export async function attachDocumentToCompany(
  companyId: string,
  documentId: string,
): Promise<ProspectDocument> {
  return api<ProspectDocument>(`/companies/${companyId}/documents`, {
    method: "POST",
    body: JSON.stringify({ document_id: documentId }),
  });
}

export async function detachDocumentFromCompany(
  companyId: string,
  documentId: string,
): Promise<void> {
  return api<void>(`/companies/${companyId}/documents/${documentId}`, {
    method: "DELETE",
  });
}

// ==========================================
// 6. Watchlist Types & API
// ==========================================

// WatchlistCompanyOut: GET /watchlist, POST /watchlist. Each amount carries its own currency
// (as its source states it); the company's reporting currency is context only. Never converted.
export type WatchlistEntry = {
  company_id: string;
  name: string;
  ticker: string | null;
  country: string | null;
  reporting_currency: string | null;
  currency: string | null; // of `revenue`
  latest_period: string | null;
  revenue: string | null; // decimal string, full currency units
  revenue_formatted: string | null;
  net_income: string | null;
  net_income_currency: string | null; // may differ from revenue's
  net_income_formatted: string | null;
  revenue_yoy_change: string | null; // plain ratio, e.g. "0.148"; null across currencies
  revenue_yoy_change_formatted: string | null;
  created_at: string;
};

export async function listWatchlist(): Promise<WatchlistEntry[]> {
  return api<WatchlistEntry[]>("/watchlist");
}

export async function addToWatchlist(companyId: string): Promise<WatchlistEntry> {
  return api<WatchlistEntry>("/watchlist", {
    method: "POST",
    body: JSON.stringify({ company_id: companyId }),
  });
}

export async function removeFromWatchlist(companyId: string): Promise<void> {
  return api<void>(`/watchlist/${companyId}`, {
    method: "DELETE",
  });
}

// ==========================================
// 7. Audit Trail Types & API
// ==========================================

export type AuditEvent = {
  id: string;
  actor_id: string | null;
  event_type: string;
  entity_type: string;
  entity_id: string;
  before_state: Record<string, unknown> | null;
  after_state: Record<string, unknown> | null;
  reason: string | null;
  ip_address: string | null;
  timestamp: string;
};

export async function listAuditEvents(
  params: Record<string, string | number | undefined> = {},
): Promise<{ items: AuditEvent[]; total: number }> {
  const query = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") query.set(k, String(v));
  }
  const qStr = query.toString();
  return api<{ items: AuditEvent[]; total: number }>(`/audit${qStr ? `?${qStr}` : ""}`);
}

// ==========================================
// 8. Pure Deterministic Helper Functions
// ==========================================

/**
 * Deterministic badge representation for anomaly severities.
 * Always combines text and symbol so it does not rely on color alone.
 */
export function anomalySeverityBadge(severity: AnomalySeverity): {
  symbol: string;
  label: string;
  className: string;
} {
  switch (severity) {
    case "error":
      return { symbol: "✕", label: "Error", className: "bg-red-50 text-red-700 border-red-200" };
    case "warning":
      return {
        symbol: "⚠",
        label: "Warning",
        className: "bg-amber-50 text-amber-700 border-amber-200",
      };
    case "info":
      return { symbol: "ℹ", label: "Info", className: "bg-blue-50 text-blue-700 border-blue-200" };
  }
}

/**
 * Deterministic status indicator for section diff items.
 */
export function sectionDiffBadge(status: SectionDiffStatus): {
  symbol: string;
  label: string;
  className: string;
} {
  switch (status) {
    case "added":
      return {
        symbol: "+",
        label: "Added",
        className: "bg-emerald-50 text-emerald-700 border-emerald-200",
      };
    case "removed":
      return {
        symbol: "−",
        label: "Removed",
        className: "bg-rose-50 text-rose-700 border-rose-200",
      };
    case "changed":
      return {
        symbol: "~",
        label: "Changed",
        className: "bg-amber-50 text-amber-700 border-amber-200",
      };
    case "unchanged":
      return {
        symbol: "=",
        label: "Unchanged",
        className: "bg-slate-50 text-slate-600 border-slate-200",
      };
  }
}

/**
 * Deterministic confidence label from score string.
 */
export function formatConfidence(score: string): {
  label: "High" | "Medium" | "Low";
  score: string;
} {
  const num = Number.parseFloat(score);
  if (Number.isNaN(num)) return { label: "Medium", score };
  if (num >= 0.85) return { label: "High", score };
  if (num >= 0.6) return { label: "Medium", score };
  return { label: "Low", score };
}
