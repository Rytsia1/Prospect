"use client";

import Link from "next/link";
import { type DragEvent, useState } from "react";
import { ApiError, api, type DocumentUpload, putWithProgress } from "@/lib/api";
import {
  DOCUMENT_TYPE_LABEL,
  type DocumentType,
  formatBytes,
  type ProspectDocument,
  validatePdf,
} from "@/lib/documents";

type State =
  | { phase: "idle" }
  | { phase: "uploading"; file: File; loaded: number }
  | { phase: "verifying"; file: File }
  | { phase: "done"; document: ProspectDocument }
  | { phase: "error"; file?: File; message: string; retry?: () => void };

export function Upload({ onUploaded }: { onUploaded: () => void }) {
  const [state, setState] = useState<State>({ phase: "idle" });
  const [dragging, setDragging] = useState(false);
  const [documentType, setDocumentType] = useState<DocumentType>("annual_report");
  const [fiscalYear, setFiscalYear] = useState("");
  const [company, setCompany] = useState("");
  const busy = state.phase === "uploading" || state.phase === "verifying";

  async function start(file: File) {
    const invalid = validatePdf(file);
    if (invalid) return setState({ phase: "error", file, message: invalid });
    setState({ phase: "uploading", file, loaded: 0 });
    try {
      const created = await api<DocumentUpload>("/documents", {
        method: "POST",
        body: JSON.stringify({
          filename: file.name,
          content_type: "application/pdf",
          size_bytes: file.size,
          document_type: documentType,
          fiscal_year: fiscalYear ? Number(fiscalYear) : null,
          company_name: company.trim() || null,
        }),
      });
      onUploaded(); // show the UPLOADING row in the list right away
      await sendAndComplete(file, created);
    } catch (e) {
      fail(file, e, () => start(file));
    }
  }

  async function sendAndComplete(file: File, created: DocumentUpload) {
    // Retrying reuses the signed URL while it is valid, otherwise starts a fresh upload.
    const retry = () =>
      Date.parse(created.upload.expires_at) > Date.now()
        ? sendAndComplete(file, created)
        : start(file);
    try {
      setState({ phase: "uploading", file, loaded: 0 });
      await putWithProgress(created.upload, file, (loaded) =>
        setState({ phase: "uploading", file, loaded }),
      );
      setState({ phase: "verifying", file });
      const document = await api<ProspectDocument>(`/documents/${created.document.id}/complete`, {
        method: "POST",
      });
      setState({ phase: "done", document });
    } catch (e) {
      // A stored file that fails server verification will fail again; don't offer a retry.
      fail(file, e, e instanceof ApiError && e.code === "invalid_upload" ? undefined : retry);
    }
    onUploaded();
  }

  function fail(file: File, e: unknown, retry?: () => void) {
    const message = e instanceof ApiError ? e.message : "Something went wrong.";
    setState({ phase: "error", file, message, retry });
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && !busy) start(file);
  }

  return (
    <section aria-labelledby="upload-heading" className="space-y-3">
      <h2 id="upload-heading" className="sr-only">
        Upload a document
      </h2>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex items-center gap-2">
          <span className="text-slate-600">Type</span>
          <select
            value={documentType}
            onChange={(e) => setDocumentType(e.target.value as DocumentType)}
            disabled={busy}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {Object.entries(DOCUMENT_TYPE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-2">
          <span className="text-slate-600">Fiscal year</span>
          <input
            type="number"
            min={1900}
            max={2200}
            placeholder="Optional"
            value={fiscalYear}
            onChange={(e) => setFiscalYear(e.target.value)}
            disabled={busy}
            className="w-28 rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex items-center gap-2">
          <span className="text-slate-600">Company</span>
          <input
            type="text"
            maxLength={200}
            placeholder="Optional; groups reports"
            value={company}
            onChange={(e) => setCompany(e.target.value)}
            disabled={busy}
            className="w-56 rounded border border-slate-300 px-2 py-1"
          />
        </label>
      </div>

      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        className={`block cursor-pointer rounded border-2 border-dashed px-6 py-10 text-center focus-within:ring-2 focus-within:ring-slate-400 ${
          dragging ? "border-slate-500 bg-slate-50" : "border-slate-300"
        } ${busy ? "pointer-events-none opacity-60" : ""}`}
      >
        <input
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          disabled={busy}
          onChange={(e) => {
            const file = e.target.files?.[0];
            e.target.value = ""; // allow choosing the same file again
            if (file) start(file);
          }}
        />
        <span className="block font-medium">Drop an annual report here</span>
        <span className="mt-1 block text-sm text-slate-600">
          or <span className="underline">choose a PDF</span> (up to 50 MB)
        </span>
      </label>

      <div role="status" aria-live="polite">
        <UploadStatus state={state} />
      </div>
    </section>
  );
}

function UploadStatus({ state }: { state: State }) {
  if (state.phase === "idle") return null;
  if (state.phase === "done") {
    return (
      <p className="text-sm">
        <Link href={`/documents/${state.document.id}`} className="font-medium underline">
          {state.document.filename}
        </Link>{" "}
        uploaded. Queued for processing.
      </p>
    );
  }
  const file = state.file;
  return (
    <div className="space-y-2 rounded border border-slate-200 p-3 text-sm">
      {file && (
        <p className="font-medium">
          {file.name} <span className="font-normal text-slate-500">· {formatBytes(file.size)}</span>
        </p>
      )}
      {state.phase === "uploading" && file && (
        <>
          <progress className="h-2 w-full" max={file.size} value={state.loaded} />
          <p className="text-slate-600">
            Uploading… {formatBytes(state.loaded)} of {formatBytes(file.size)}
          </p>
        </>
      )}
      {state.phase === "verifying" && <p className="text-slate-600">Verifying file…</p>}
      {state.phase === "error" && (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-red-800">{state.message}</p>
          {state.retry && (
            <button
              type="button"
              onClick={state.retry}
              className="rounded border border-slate-300 px-3 py-1 hover:bg-slate-50"
            >
              Retry
            </button>
          )}
        </div>
      )}
    </div>
  );
}
