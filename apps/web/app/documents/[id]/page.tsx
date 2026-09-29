import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentDetail } from "@/components/document-detail";
import { parseEvidenceKey, TABS } from "@/lib/financials";

export const metadata: Metadata = { title: "Document" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{
    page?: string;
    tab?: string;
    scope?: string;
    period?: string;
    evidence?: string;
  }>;
};

export default async function DocumentPage({ params, searchParams }: Props) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  const query = await searchParams;
  const page = Number.parseInt(query.page ?? "1", 10);
  const tab = TABS.find(([key]) => key === query.tab)?.[0] ?? "overview";
  return (
    <DocumentDetail
      id={id}
      initial={{
        tab,
        scope: query.scope === "company" ? "company" : "document",
        period: query.period ?? null,
        page: Number.isFinite(page) && page > 0 ? page : 1,
        evidence: parseEvidenceKey(query.evidence) ? (query.evidence ?? null) : null,
      }}
    />
  );
}
