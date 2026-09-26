import Link from "next/link";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

async function apiReachable(): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}/health`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    return res.ok;
  } catch {
    return false;
  }
}

const LAYERS = [
  {
    label: "Fact",
    color: "border-fact text-fact",
    text: "A value extracted from the document, with its page and section.",
  },
  {
    label: "Calculation",
    color: "border-calc text-calc",
    text: "Computed by Prospect from facts, with the formula and inputs shown.",
  },
  {
    label: "Interpretation",
    color: "border-interp text-interp",
    text: "An explanation grounded in cited evidence. Never a source of numbers.",
  },
];

export default async function Home() {
  const reachable = await apiReachable();
  return (
    <div className="space-y-10">
      <section className="max-w-2xl space-y-3">
        <h1 className="text-3xl font-semibold tracking-tight">Financial research you can verify</h1>
        <p className="text-slate-600">
          Prospect reads annual reports, financial statements, and prospectuses. Every figure it
          shows links back to the page it came from.
        </p>
        <Link
          href="/documents"
          className="inline-block rounded bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Go to documents
        </Link>
      </section>

      <section aria-labelledby="layers" className="space-y-3">
        <h2 id="layers" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          How answers are structured
        </h2>
        <ul className="grid gap-3 sm:grid-cols-3">
          {LAYERS.map(({ label, color, text }) => (
            <li key={label} className={`border-l-4 bg-slate-50 p-4 ${color}`}>
              <p className="text-xs font-semibold uppercase tracking-wide">{label}</p>
              <p className="mt-1 text-sm text-slate-700">{text}</p>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-xs text-slate-500" role="status">
        API: {reachable ? "reachable" : "unreachable"}
      </p>
    </div>
  );
}
