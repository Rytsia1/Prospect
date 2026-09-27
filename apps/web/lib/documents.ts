// Pure document helpers (no DOM, no fetch) so they run under `node --test`.

export type DocumentStatus =
  | "UPLOADING"
  | "UPLOADED"
  | "QUEUED"
  | "PROCESSING"
  | "EXTRACTING"
  | "INDEXING"
  | "READY"
  | "FAILED";

export type DocumentType = "annual_report" | "financial_statement" | "prospectus";

export type ProspectDocument = {
  id: string;
  filename: string;
  document_type: DocumentType;
  fiscal_year: number | null;
  company_name: string | null;
  company_id?: string | null;
  mime_type: string;
  size_bytes: number;
  status: DocumentStatus;
  processing_error: string | null;
  created_at: string;
  updated_at: string;
};

export const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  annual_report: "Annual report",
  financial_statement: "Financial statement",
  prospectus: "Prospectus",
};

export const STATUS_LABEL: Record<DocumentStatus, string> = {
  UPLOADING: "Uploading",
  UPLOADED: "Queued for processing",
  QUEUED: "Queued for processing",
  PROCESSING: "Processing",
  EXTRACTING: "Processing",
  INDEXING: "Processing",
  READY: "Ready",
  FAILED: "Failed",
};

export function isSettled(status: DocumentStatus): boolean {
  return status === "READY" || status === "FAILED";
}

// UX pre-check only; the API (MAX_UPLOAD_BYTES) and stored-byte checks are authoritative.
export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024;

export function validatePdf(file: { name: string; type: string; size: number }): string | null {
  const looksLikePdf =
    file.type === "application/pdf" || (file.type === "" && /\.pdf$/i.test(file.name));
  if (!looksLikePdf) return "Only PDF files are supported.";
  if (file.size === 0) return "The file is empty.";
  if (file.size > MAX_UPLOAD_BYTES) {
    return `The file is larger than the ${MAX_UPLOAD_BYTES / 1024 / 1024} MB limit.`;
  }
  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export type PageExtractionStatus = "success" | "partial" | "failed";

export type PageSummary = {
  page_number: number;
  label: string | null;
  extraction_status: PageExtractionStatus;
  char_count: number;
};

export type DocumentPage = {
  page_number: number;
  label: string | null;
  extraction_status: PageExtractionStatus;
  text: string;
  width: number | null;
  height: number | null;
};

export type DocumentSection = {
  id: string;
  ordinal: number;
  title: string | null;
  start_page: number;
  end_page: number;
};

/** Printed page label worth showing: only when the PDF defines one that differs from the index. */
export function printedLabel(page: { page_number: number; label: string | null }): string | null {
  return page.label && page.label !== String(page.page_number) ? page.label : null;
}

export type FactStatus = "accepted" | "needs_review" | "corrected" | "rejected";

export type FinancialFact = {
  id: string;
  document_id: string;
  metric: string;
  metric_name: string;
  value: string; // decimal string, full value in currency units; never parsed into a float
  currency: string | null;
  scale: string;
  original_text: string;
  period_type: "annual" | "quarter" | "interim" | "instant";
  period_label: string;
  period_end: string | null;
  fiscal_year: number | null;
  confidence: string;
  status: FactStatus;
  review_reasons: string[];
  extraction_method: string;
  evidence: {
    id: string;
    page_number: number;
    page_label: string | null;
    section_title: string | null;
    chunk_id: string;
    kind: string;
    content: string;
    header: string | null;
    unit: string | null;
  };
};

export const METRIC_ORDER = [
  "revenue",
  "gross_profit",
  "operating_income",
  "net_income",
  "total_assets",
  "current_assets",
  "current_liabilities",
  "total_liabilities",
  "equity",
  "cash",
  "total_debt",
];

const CURRENCY_SYMBOL: Record<string, string> = { IDR: "Rp", USD: "US$" };

function splitDecimal(value: string): { negative: boolean; digits: string; fraction: string } {
  const negative = value.startsWith("-");
  const [int, fraction = ""] = value.replace(/^-/, "").split(".");
  return { negative, digits: int.replace(/^0+(?=\d)/, ""), fraction: fraction.replace(/0+$/, "") };
}

function currencyPrefix(currency: string | null): string {
  return currency ? (CURRENCY_SYMBOL[currency] ?? `${currency} `) : "";
}

/** Compact display (Rp12.4T), rounded half-up to two decimals with integer math only. */
export function formatAmount(value: string, currency: string | null): string {
  const { negative, digits, fraction } = splitDecimal(value);
  const units: [number, string][] = [
    [12, "T"],
    [9, "B"],
    [6, "M"],
  ];
  const unit = units.find(([exp]) => digits.length > exp);
  let body: string;
  if (unit) {
    const [exp, suffix] = unit;
    const divisor = 10n ** BigInt(exp - 2);
    const hundredths = (BigInt(digits) + divisor / 2n) / divisor;
    const whole = hundredths / 100n;
    const cents = (hundredths % 100n).toString().padStart(2, "0").replace(/0+$/, "");
    body = `${whole}${cents ? `.${cents}` : ""}${suffix}`;
  } else {
    body = `${digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",")}${fraction ? `.${fraction}` : ""}`;
  }
  return `${negative ? "−" : ""}${currencyPrefix(currency)}${body}`;
}

/** Full value with grouping, e.g. Rp12,400,000,000,000 — what the compact form stands for. */
export function formatExact(value: string, currency: string | null): string {
  const { negative, digits, fraction } = splitDecimal(value);
  const grouped = digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative ? "−" : ""}${currencyPrefix(currency)}${grouped}${fraction ? `.${fraction}` : ""}`;
}

export type Calculation = {
  id: string;
  metric: string;
  name: string;
  formula_key: string;
  formula: string;
  period_type: FinancialFact["period_type"];
  period_label: string;
  status: "calculated" | "not_possible";
  value: string | null; // plain ratio at full precision, as a decimal string
  unit: "percent" | "times";
  reason_code: string | null;
  reason: string | null;
  notes: string[];
  inputs: FinancialFact[];
};

/** value × 10^shift rounded half away from zero to `places` decimals, using integer math only. */
export function roundDecimal(value: string, shift: number, places: number): string {
  const negative = value.startsWith("-");
  const [int, fraction = ""] = value.replace(/^[-+]/, "").split(".");
  const keep = shift + places;
  const scaled = BigInt(int + fraction.padEnd(keep + 1, "0").slice(0, keep + 1)); // one extra digit
  const rounded = (scaled + 5n) / 10n;
  const digits = rounded.toString().padStart(places + 1, "0");
  const body = places ? `${digits.slice(0, -places)}.${digits.slice(-places)}` : digits;
  return `${negative && rounded !== 0n ? "−" : ""}${body}`;
}

/** Display a stored ratio: 0.18095… → "18.10%" (or "+18.10%" for growth), 1.25 → "1.25x". */
export function formatRatio(value: string, unit: Calculation["unit"], signed = false): string {
  const text =
    unit === "percent" ? `${roundDecimal(value, 2, 2)}%` : `${roundDecimal(value, 0, 2)}x`;
  return signed && !text.startsWith("−") && !/^0\.00/.test(text) ? `+${text}` : text;
}

/** Hex SHA-256 of the file, sent with the upload so the server can verify the stored bytes. */
export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", data));
  return Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("");
}
