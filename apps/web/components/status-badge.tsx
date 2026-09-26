import { type DocumentStatus, STATUS_LABEL } from "@/lib/documents";

const TONE: Record<DocumentStatus, string> = {
  UPLOADING: "bg-slate-100 text-slate-700",
  UPLOADED: "bg-slate-100 text-slate-700",
  QUEUED: "bg-slate-100 text-slate-700",
  PROCESSING: "bg-blue-50 text-blue-800",
  EXTRACTING: "bg-blue-50 text-blue-800",
  INDEXING: "bg-blue-50 text-blue-800",
  READY: "bg-emerald-50 text-emerald-800",
  FAILED: "bg-red-50 text-red-800",
};

export function StatusBadge({ status }: { status: DocumentStatus }) {
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${TONE[status]}`}>
      {STATUS_LABEL[status]}
    </span>
  );
}
