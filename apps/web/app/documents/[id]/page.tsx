import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

export const metadata: Metadata = { title: "Document" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function Pane({ title, empty }: { title: string; empty: string }) {
  return (
    <section aria-label={title} className="rounded border border-slate-200">
      <h2 className="border-b border-slate-200 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {title}
      </h2>
      <p className="px-3 py-8 text-center text-sm text-slate-500">{empty}</p>
    </section>
  );
}

export default async function DocumentWorkspace({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  // Workspace layout from docs/UX_SPEC.md §5; columns stack below the lg breakpoint.
  return (
    <div className="space-y-4">
      <div>
        <Link href="/documents" className="text-sm text-slate-600 hover:text-slate-900">
          ← Documents
        </Link>
        <h1 className="mt-1 font-mono text-sm text-slate-500">{id}</h1>
      </div>
      <div className="grid gap-4 lg:grid-cols-[14rem_1fr_20rem]">
        <Pane title="Sections" empty="No sections detected." />
        <Pane title="Document" empty="No pages available." />
        <Pane title="Evidence" empty="No extracted facts." />
      </div>
    </div>
  );
}
