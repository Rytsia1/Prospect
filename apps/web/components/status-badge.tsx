import {
  type DocumentStatus,
  PROCESSING_STEPS,
  processingStep,
  STATUS_LABEL,
} from "@/lib/documents";

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

/** Where a document is in the pipeline: real states only, no invented percentage. */
export function ProcessingSteps({ status }: { status: DocumentStatus }) {
  const current = processingStep(status);
  if (current === null) return null;
  return (
    <ol aria-label="Processing progress" className="flex flex-wrap items-center gap-2 text-sm">
      {PROCESSING_STEPS.map((label, i) => {
        const done = i < current || status === "READY";
        return (
          <li
            key={label}
            aria-current={i === current && !done ? "step" : undefined}
            className="flex items-center gap-2"
          >
            {i > 0 && <span aria-hidden="true" className="h-px w-6 bg-slate-300" />}
            <span
              className={
                done
                  ? "text-emerald-800"
                  : i === current
                    ? "font-medium text-slate-900"
                    : "text-slate-400"
              }
            >
              {done ? "✓ " : i === current ? "● " : ""}
              {label}
              {i === current && !done && <span className="sr-only"> (in progress)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
