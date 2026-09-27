import { formatAmount, formatExact } from "@/lib/documents";
import { chartPoints } from "@/lib/financials";

const WIDTH = 640;
const HEIGHT = 180;
const PAD = 32;

type Point = { period: string; value: string | null; currency: string | null };

/** A line of reported values across periods. Gaps (missing, conflicting) stay gaps. */
export function TrendChart({ title, points }: { title: string; points: Point[] }) {
  if (!points.some((p) => p.value)) {
    return <p className="text-sm text-slate-500">No reported values for {title.toLowerCase()}.</p>;
  }
  const xy = chartPoints(
    points.map((p) => p.value),
    WIDTH,
    HEIGHT,
    PAD,
  );
  const path = xy
    .map((p, i) => (p ? `${i > 0 && xy[i - 1] ? "L" : "M"}${p.x},${p.y}` : ""))
    .join(" ");
  const step = (WIDTH - 2 * PAD) / Math.max(points.length - 1, 1);
  const described = points
    .map((p) => `${p.period}: ${p.value ? formatExact(p.value, p.currency) : "no value"}`)
    .join("; ");

  return (
    <figure className="space-y-1">
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT + 20}`}
        className="h-auto w-full max-w-2xl"
        role="img"
        aria-label={`${title} by period. ${described}`}
      >
        <line x1={PAD} x2={WIDTH - PAD} y1={HEIGHT} y2={HEIGHT} className="stroke-slate-200" />
        <path d={path} fill="none" className="stroke-fact" strokeWidth={2} />
        {points.map((point, i) => {
          const p = xy[i];
          const x = points.length > 1 ? PAD + i * step : WIDTH / 2;
          return (
            <g key={point.period}>
              {p && point.value && (
                <>
                  <circle cx={p.x} cy={p.y} r={4} className="fill-fact" />
                  <text
                    x={p.x}
                    y={p.y - 10}
                    textAnchor="middle"
                    className="fill-slate-700 text-[11px]"
                  >
                    {formatAmount(point.value, point.currency)}
                  </text>
                </>
              )}
              <text
                x={x}
                y={HEIGHT + 16}
                textAnchor="middle"
                className="fill-slate-500 text-[11px]"
              >
                {point.period}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="text-xs text-slate-500">
        {title}: reported values (FACT). Periods without a single agreed value are gaps.
      </figcaption>
    </figure>
  );
}
