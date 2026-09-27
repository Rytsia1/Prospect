import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { CalculationExplorer } from "@/components/calculation-explorer";

export const metadata: Metadata = { title: "Calculation" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Props = {
  params: Promise<{ id: string; key: string }>;
  searchParams: Promise<{ period?: string; scope?: string }>;
};

export default async function CalculationPage({ params, searchParams }: Props) {
  const { id, key } = await params;
  const { period, scope } = await searchParams;
  if (!UUID.test(id) || !period) notFound();
  return (
    <CalculationExplorer
      documentId={id}
      calculationKey={decodeURIComponent(key)}
      period={period}
      scope={scope === "company" ? "company" : "document"}
    />
  );
}
