export default function Loading() {
  return (
    <div role="status" aria-live="polite" className="space-y-3">
      <span className="sr-only">Loading…</span>
      <div className="h-7 w-48 animate-pulse rounded bg-slate-100" />
      <div className="h-4 w-80 max-w-full animate-pulse rounded bg-slate-100" />
    </div>
  );
}
