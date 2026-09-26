const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export const dynamic = "force-dynamic";

async function apiStatus(): Promise<string> {
  try {
    const res = await fetch(`${API_URL}/health`, { cache: "no-store" });
    return res.ok ? "API reachable" : `API error (${res.status})`;
  } catch {
    return "API unreachable";
  }
}

export default async function Home() {
  const status = await apiStatus();
  return (
    <section className="space-y-4">
      <h1 className="text-2xl font-semibold">Documents</h1>
      <p className="text-slate-600">
        Upload annual reports, financial statements, and prospectuses. Every figure links back to
        its source page.
      </p>
      <p className="text-sm text-slate-500">Status: {status}</p>
    </section>
  );
}
