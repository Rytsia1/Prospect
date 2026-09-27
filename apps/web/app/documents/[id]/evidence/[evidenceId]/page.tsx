import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { EvidenceExplorer } from "@/components/evidence-explorer";

export const metadata: Metadata = { title: "Evidence" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Props = { params: Promise<{ id: string; evidenceId: string }> };

export default async function EvidencePage({ params }: Props) {
  const { id, evidenceId } = await params;
  if (!UUID.test(id) || !UUID.test(evidenceId)) notFound();
  return <EvidenceExplorer documentId={id} evidenceId={evidenceId} />;
}
