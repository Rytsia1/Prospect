import { DocumentsView } from "@/components/documents-view";

// The first screen is the first step: upload a report, or open one uploaded from this browser.
export default function Home() {
  return (
    <div className="space-y-8">
      <section className="max-w-2xl space-y-2">
        <h1 className="text-3xl font-semibold tracking-tight">Financial research you can verify</h1>
        <p className="text-slate-600">
          Upload an annual report, financial statement or prospectus. Every figure Prospect shows
          links back to the page it came from.
        </p>
      </section>
      <DocumentsView />
    </div>
  );
}
