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
