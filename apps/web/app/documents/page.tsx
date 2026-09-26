import type { Metadata } from "next";

export const metadata: Metadata = { title: "Documents" };

export default function DocumentsPage() {
  // ponytail: static empty state until GET /api/v1/documents exists (Phase 1).
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Documents</h1>
        <button
          type="button"
          disabled
          title="Upload arrives in the next release"
          className="rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          Upload PDF
        </button>
      </div>
      <div className="rounded border border-dashed border-slate-300 px-6 py-16 text-center">
        <p className="font-medium">No documents yet.</p>
        <p className="mt-1 text-sm text-slate-600">Upload an annual report to start researching.</p>
      </div>
    </div>
  );
}
