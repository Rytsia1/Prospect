import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { DocumentDetail } from "@/components/document-detail";

export const metadata: Metadata = { title: "Document" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export default async function DocumentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!UUID.test(id)) notFound();
  return <DocumentDetail id={id} />;
}
