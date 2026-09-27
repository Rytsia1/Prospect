import Link from "next/link";
import { CalculationBadge } from "@/components/calculations-panel";
import { FactBadge } from "@/components/facts-panel";
import {
  CellValue,
  ChangeLine,
  EvidenceLink,
  ResultValue,
  SourceList,
} from "@/components/financial-values";
import { TrendChart } from "@/components/trend-chart";
import {
  calculationPath,
  type Financials,
  indexFinancials,
  QUALITY_SYMBOL,
  type Scope,
} from "@/lib/financials";

const GROUPS: [string, string[]][] = [
  ["Income", ["revenue", "gross_profit", "operating_income", "net_income"]],
  ["Balance sheet", ["total_assets", "total_liabilities", "equity", "cash"]],
  ["Leverage and liquidity", ["total_debt", "calc:debt_to_equity", "calc:current_ratio"]],
  ["Profitability and growth", ["calc:net_margin", "calc:roa", "calc:roe", "calc:revenue_growth"]],
];

type Props = {
  fin: Financials;
  documentId: string;
  scope: Scope;
  period: string;
  onPeriod: (period: string) => void;
};

export function PeriodSelect({
  fin,
  period,
  onPeriod,
}: {
  fin: Financials;
  period: string;
  onPeriod: (period: string) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-slate-600">Period</span>
      <select
        value={period}
        onChange={(e) => onPeriod(e.target.value)}
        className="rounded border border-slate-300 px-2 py-1"
      >
        {[...fin.periods].reverse().map((p) => (
          <option key={p} value={p}>
            {p}
            {fin.period_basis[p] === "date" ? " (balance date; fiscal year not stated)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

function CalculationCard(props: {
  fin: Financials;
  metric: string;
  documentId: string;
  scope: Scope;
  period: string;
}) {
  const { fin, metric, documentId, scope, period } = props;
  const index = indexFinancials(fin);
  const result = index.calculation(metric, period);
  if (!result) return null; // this ratio has no period of this kind
  const inputs = result.input_fact_ids.map((i) => index.fact(i)).filter((f) => f !== undefined);
  return (
    <li className="rounded border border-slate-200 px-3 py-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium">{result.name}</p>
        <CalculationBadge />
      </div>
      <p className="mt-1 text-xl font-semibold">
        <ResultValue result={result} signed={result.metric === "revenue_growth"} />
      </p>
      {result.status === "not_possible" ? (
        <p className="text-xs text-slate-600">{result.reason}</p>
      ) : (
        <p className="text-xs text-slate-600">
          Based on{" "}
          {inputs.map((f) => `${f.metric_name.toLowerCase()} ${f.period_label}`).join(", ")}.
        </p>
      )}
      {result.notes.map((n) => (
        <p key={n} className="text-xs text-amber-900">
          {n}
        </p>
      ))}
      <Link
        href={calculationPath(documentId, scope, result.metric, period)}
        className="mt-1 inline-block text-xs text-calc underline underline-offset-2"
      >
        View source inputs
      </Link>
    </li>
  );
}

function FactCard(props: {
  fin: Financials;
  metric: string;
  documentId: string;
  scope: Scope;
  period: string;
}) {
  const { fin, metric, documentId, scope, period } = props;
  const index = indexFinancials(fin);
  const cell = index.cell(metric, period);
  const fact = index.fact(cell?.primary_fact_id);
  const documents = new Map(fin.documents.map((d) => [d.id, d.filename]));
  return (
    <li className="rounded border border-slate-200 px-3 py-3 text-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="font-medium">{fin.metrics.find((m) => m.key === metric)?.name}</p>
        <FactBadge />
      </div>
      <div className={fact ? "mt-1 text-xl font-semibold" : "mt-1"}>
        <CellValue cell={cell} index={index} />
      </div>
      {cell && !fact && (
        <div className="mt-1 text-xs">
          <SourceList cell={cell} index={index} documents={documents} />
        </div>
      )}
      {cell && <ChangeLine cell={cell} documentId={documentId} scope={scope} />}
      {fact && (
        <p className="mt-1 text-xs">
          <EvidenceLink fact={fact} label="View evidence" />
        </p>
      )}
    </li>
  );
}

export function Dashboard({ fin, documentId, scope, period, onPeriod }: Props) {
  const index = indexFinancials(fin);
  const revenue = fin.periods.map((p) => {
    const fact = index.fact(index.cell("revenue", p)?.primary_fact_id);
    return { period: p, value: fact?.value ?? null, currency: fact?.currency ?? null };
  });

  return (
    <section aria-labelledby="overview-heading" className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="overview-heading" className="text-lg font-semibold">
            Financial overview · {period}
          </h2>
          <p className="text-xs text-slate-500">
            <FactBadge /> printed in the source · <CalculationBadge /> computed by Prospect from
            those facts. No investment view is expressed.
          </p>
        </div>
        <PeriodSelect fin={fin} period={period} onPeriod={onPeriod} />
      </div>

      {GROUPS.map(([title, keys]) => (
        <div key={title} className="space-y-2">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h3>
          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {keys.map((key) =>
              key.startsWith("calc:") ? (
                <CalculationCard
                  key={key}
                  fin={fin}
                  metric={key.slice(5)}
                  documentId={documentId}
                  scope={scope}
                  period={period}
                />
              ) : (
                <FactCard
                  key={key}
                  fin={fin}
                  metric={key}
                  documentId={documentId}
                  scope={scope}
                  period={period}
                />
              ),
            )}
          </ul>
        </div>
      ))}

      <div className="space-y-2">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Revenue trend
        </h3>
        <TrendChart title="Revenue" points={revenue} />
      </div>

      <DataQuality fin={fin} period={period} />
    </section>
  );
}

export function DataQuality({ fin, period }: { fin: Financials; period?: string }) {
  const items = fin.quality.filter((q) => !period || q.period === period);
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Data quality{period ? ` · ${period}` : ""}
      </h3>
      <p className="text-xs text-slate-500">
        Checks on the extracted data, not on the company. Descriptive only.
      </p>
      {items.length === 0 ? (
        <p className="text-sm text-slate-500">No checks for this period.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {items.map((q) => (
            <li
              key={`${q.period}|${q.message}`}
              className={q.level === "warning" ? "text-amber-900" : "text-slate-700"}
            >
              <span aria-hidden="true" className="mr-2 inline-block w-4 text-center">
                {QUALITY_SYMBOL[q.level]}
              </span>
              <span className="sr-only">{q.level === "ok" ? "OK: " : `${q.level}: `}</span>
              {!period && <span className="mr-1 text-slate-500">{q.period}:</span>}
              {q.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
