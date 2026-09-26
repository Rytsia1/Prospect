"use client";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="max-w-lg space-y-3">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-sm text-slate-600">This page could not be loaded. Try again.</p>
      <button
        type="button"
        onClick={reset}
        className="rounded border border-slate-300 px-4 py-2 text-sm hover:bg-slate-50"
      >
        Try again
      </button>
    </div>
  );
}
