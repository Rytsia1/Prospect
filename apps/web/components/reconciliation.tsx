import { DataQuality } from "@/components/dashboard";
import { EvidenceLink } from "@/components/financial-values";
import { formatExact } from "@/lib/documents";
import { type Financials, indexFinancials, RECONCILIATION_TEXT } from "@/lib/financials";

const INPUTS = [
  ["total_assets", "Total assets"],
  ["total_liabilities", "Total liabilities"],
  ["equity", "Total equity"],
] as const;

const STATUS_STYLE = {
  BALANCED: "border-emerald-300 text-emerald-900",
  ROUNDING_DIFFERENCE: "border-emerald-300 text-emerald-900",
  MISMATCH: "border-red-300 text-red-900",
  INSUFFICIENT_DATA: "border-slate-300 text-slate-700",
};

export function ReconciliationView({ fin }: { fin: Financials }) {
  const index = indexFinancials(fin);
  return (
    <section aria-labelledby="reconciliation-heading" className="space-y-6">
      <div>
        <h2 id="reconciliation-heading" className="text-lg font-semibold">
          Balance sheet reconciliation
        </h2>
        <p className="text-xs text-slate-500">
          A consistency check on the extracted figures (assets = liabilities + equity), not an
          audit. Differences within the printed-figure rounding tolerance are reported as rounding
          differences; anything larger is a mismatch. Missing values are never treated as zero.
          Cash-flow reconciliation is not performed: cash-flow lines are not extracted yet.
        </p>
      </div>

      {fin.reconciliations.length === 0 ? (
        <p className="text-sm text-slate-600">No balance-sheet facts in scope.</p>
      ) : (
        <ul className="grid gap-4 lg:grid-cols-2">
          {[...fin.reconciliations].reverse().map((rec) => {
            const text = RECONCILIATION_TEXT[rec.status];
            return (
              <li key={rec.period} className="rounded border border-slate-200 px-4 py-3 text-sm">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="font-semibold">{rec.period}</h3>
                  <span
                    className={`rounded border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[rec.status]}`}
                  >
                    <span aria-hidden="true">{text.symbol} </span>
                    {rec.status}
                  </span>
                </div>
                <p className="sr-only">Status: {text.label}</p>
                <table className="mt-2 w-full">
                  <caption className="sr-only">Reconciliation inputs for {rec.period}</caption>
                  <tbody className="divide-y divide-slate-100">
                    {INPUTS.map(([metric, name]) => {
                      const fact = index.fact(rec.fact_ids[metric]);
                      return (
                        <tr key={metric}>
                          <th scope="row" className="py-1 text-left font-normal text-slate-600">
                            {name}
                          </th>
                          <td className="py-1 text-right">
                            {fact ? formatExact(fact.value, fact.currency) : "—"}
                          </td>
                          <td className="py-1 pl-3 text-right text-xs">
                            {fact && <EvidenceLink fact={fact} />}
                          </td>
                        </tr>
                      );
                    })}
                    {rec.liabilities_plus_equity !== null && (
                      <>
                        <tr>
                          <th scope="row" className="py-1 text-left font-normal text-slate-600">
                            Liabilities + equity
                          </th>
                          <td className="py-1 text-right">
                            {formatExact(rec.liabilities_plus_equity, rec.currency)}
                          </td>
                          <td />
                        </tr>
                        <tr>
                          <th scope="row" className="py-1 text-left font-medium">
                            Difference
                          </th>
                          <td className="py-1 text-right font-medium">
                            {formatExact(rec.difference ?? "0", rec.currency)}
                          </td>
                          <td className="py-1 pl-3 text-right text-xs text-slate-500">
                            tolerance {formatExact(rec.tolerance ?? "0", rec.currency)}
                          </td>
                        </tr>
                      </>
                    )}
                  </tbody>
                </table>
                {rec.problems.length > 0 && (
                  <ul className="mt-2 space-y-0.5 text-xs text-slate-700">
                    {rec.problems.map((p) => (
                      <li key={p}>{p}</li>
                    ))}
                  </ul>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <DataQuality fin={fin} />
    </section>
  );
}
