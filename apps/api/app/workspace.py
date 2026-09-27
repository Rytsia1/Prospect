"""Multi-document financial view: timeline, dashboard, reconciliation, data quality.

Pure: no DB, no network, no LLM. Everything is derived on read from the canonical financial facts
(one row per extracted value, each with evidence); nothing here is stored, so no value can drift
from its fact. Ratios and changes come from app/analytics.py, never from here.

Merging rules (deterministic):
- periods are normalized to fiscal years (FY2025) only when the source establishes it: annual
  facts carry their fiscal year; a balance-sheet date becomes FYn only when an annual fact in scope
  ends on that date (or the balance was printed under a bare year). Otherwise the date is kept.
- the same metric and period reported by several documents (e.g. a comparative column) is one
  value when all sources agree; the primary source is the report whose own latest year it is.
- sources that disagree are a conflict: no value is chosen, every candidate is listed.
"""

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

from app.analytics import CONTEXT, FactInput, Result, calculate, year_over_year
from app.extraction import SCALES

TIMELINE_METRICS = [
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "total_assets",
    "current_assets",
    "total_liabilities",
    "current_liabilities",
    "equity",
    "cash",
    "total_debt",
]
METRIC_NAMES = {
    "revenue": "Revenue",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "current_assets": "Total current assets",
    "total_liabilities": "Total liabilities",
    "current_liabilities": "Total current liabilities",
    "equity": "Total equity",
    "cash": "Cash and cash equivalents",
    "total_debt": "Total debt",
}

ReconciliationStatus = Literal["BALANCED", "ROUNDING_DIFFERENCE", "MISMATCH", "INSUFFICIENT_DATA"]


@dataclass(frozen=True)
class SourceFact:
    """A fact from one document, as the workspace sees it."""

    fact: FactInput
    document_id: uuid.UUID
    status: Literal["accepted", "needs_review"]
    scale: str  # the presentation scale printed in the source


@dataclass(frozen=True)
class Period:
    label: str  # normalized: FY2025, or a date when no fiscal year is established
    basis: Literal["fiscal_year", "fiscal_year_end", "date"]


@dataclass
class Cell:
    metric: str
    period: str
    status: Literal["value", "conflict", "needs_review"]
    fact_ids: list[uuid.UUID]  # every source (accepted, or needs_review when none is accepted)
    primary_fact_id: uuid.UUID | None  # None unless status == "value"
    change: Result | None = None  # year-over-year, from the calculation engine


@dataclass
class Reconciliation:
    period: str
    status: ReconciliationStatus
    fact_ids: dict[str, uuid.UUID]  # total_assets / total_liabilities / equity → fact used
    liabilities_plus_equity: Decimal | None = None
    difference: Decimal | None = None  # assets − (liabilities + equity)
    tolerance: Decimal | None = None
    currency: str | None = None
    problems: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QualityItem:
    period: str
    level: Literal["ok", "warning", "info"]
    message: str
    metric: str | None = None


@dataclass
class Workspace:
    periods: list[str]  # oldest first
    period_basis: dict[str, str]
    cells: list[Cell]
    calculations: list[tuple[str, Result]]  # (normalized period, result)
    reconciliations: list[Reconciliation]
    quality: list[QualityItem]
    fact_periods: dict[uuid.UUID, str]  # every annual/balance fact → its normalized period


def _period_order(label: str) -> tuple[str, str]:
    """FY2024 < FY2025; a bare date sorts by its year among the fiscal years."""
    return (label[2:6], label) if label.startswith("FY") else (label[:4], label)


def normalize_periods(facts: list[FactInput]) -> dict[uuid.UUID, Period]:
    """Normalized period for every annual or balance-sheet fact (other period types are skipped)."""
    year_ends: dict[date, int] = {}
    for f in facts:
        if f.period_type == "annual" and f.period_end and f.fiscal_year is not None:
            year_ends[f.period_end] = f.fiscal_year
    periods: dict[uuid.UUID, Period] = {}
    for f in facts:
        if f.period_type == "annual" and f.fiscal_year is not None:
            periods[f.id] = Period(f"FY{f.fiscal_year}", "fiscal_year")
        elif f.period_type != "instant":
            continue  # quarters and interim periods are not part of the annual timeline
        elif f.period_end in year_ends:
            periods[f.id] = Period(f"FY{year_ends[f.period_end]}", "fiscal_year_end")
        elif f.period_end is None and f.fiscal_year is not None:
            periods[f.id] = Period(f"FY{f.fiscal_year}", "fiscal_year")  # printed under a year
        elif f.period_end:
            periods[f.id] = Period(f.period_end.isoformat(), "date")  # fiscal year not established
    return periods


def _primary(sources: list[SourceFact], period: str, latest: dict[uuid.UUID, str]) -> SourceFact:
    """The report whose own latest period this is; otherwise the most recent report."""

    def rank(s: SourceFact) -> tuple[bool, tuple[str, str], str]:
        doc_latest = latest[s.document_id]
        return (doc_latest == period, _period_order(doc_latest), str(s.fact.id))

    return max(sources, key=rank)


def reconcile(
    period: str,
    cells: dict[str, Cell],
    facts: dict[uuid.UUID, SourceFact],
    rounding_units: Decimal,
    relative_tolerance: Decimal,
) -> Reconciliation:
    """Assets = liabilities + equity, within a tolerance for printed-figure rounding.

    Tolerance = min(largest printed unit × rounding_units, relative_tolerance × |assets|): a
    report printed in millions may be off by a few millions from rounding, while the relative cap
    stops a coarse scale from hiding a material gap. Missing inputs are never treated as zero.
    """
    names = {
        "total_assets": "Total assets",
        "total_liabilities": "Total liabilities",
        "equity": "Total equity",
    }
    result = Reconciliation(period, "INSUFFICIENT_DATA", {})
    used: dict[str, SourceFact] = {}
    for metric, name in names.items():
        cell = cells.get(metric)
        if cell is None or cell.status == "needs_review":
            suffix = " (a value was found but needs review)" if cell else ""
            result.problems.append(f"Missing: {name} — {period}{suffix}")
        elif cell.status == "conflict":
            result.problems.append(f"{name} — {period} has conflicting values across documents")
        else:
            assert cell.primary_fact_id is not None
            used[metric] = facts[cell.primary_fact_id]
            result.fact_ids[metric] = cell.primary_fact_id
    if result.problems:
        return result
    currencies = sorted({s.fact.currency for s in used.values()})
    if len(currencies) > 1:
        result.problems.append(f"Inputs are in different currencies ({', '.join(currencies)})")
        return result

    assets = used["total_assets"].fact.value
    total = CONTEXT.add(used["total_liabilities"].fact.value, used["equity"].fact.value)
    difference = CONTEXT.subtract(assets, total)
    unit = max(SCALES[s.scale] for s in used.values())
    tolerance = min(
        CONTEXT.multiply(unit, rounding_units),
        CONTEXT.multiply(relative_tolerance, abs(assets)),
    )
    result.currency = currencies[0]
    result.liabilities_plus_equity, result.difference = total, difference
    result.tolerance = tolerance
    if difference == 0:
        result.status = "BALANCED"
    elif abs(difference) <= tolerance:
        result.status = "ROUNDING_DIFFERENCE"
    else:
        result.status = "MISMATCH"
    return result


def _reconciliation_quality(rec: Reconciliation) -> QualityItem:
    messages: dict[str, tuple[Literal["ok", "warning", "info"], str]] = {
        "BALANCED": ("ok", "Balance sheet reconciles (assets = liabilities + equity)"),
        "ROUNDING_DIFFERENCE": ("ok", "Balance sheet reconciles within rounding tolerance"),
        "MISMATCH": ("warning", "Balance sheet does not reconcile: assets ≠ liabilities + equity"),
        "INSUFFICIENT_DATA": (
            "info",
            "Balance sheet cannot be reconciled: " + "; ".join(rec.problems),
        ),
    }
    level, message = messages[rec.status]
    return QualityItem(rec.period, level, message)


def _cell_quality(cell: Cell) -> QualityItem:
    name = METRIC_NAMES[cell.metric]
    if cell.status == "value":
        n = len(cell.fact_ids)
        also = f", agreed by {n} sources" if n > 1 else ""
        return QualityItem(cell.period, "ok", f"{name} has source evidence{also}", cell.metric)
    if cell.status == "conflict":
        message = f"{name} has conflicting values across documents"
        return QualityItem(cell.period, "warning", message, cell.metric)
    return QualityItem(cell.period, "warning", f"{name} value requires review", cell.metric)


def build(
    sources: list[SourceFact],
    rounding_units: Decimal = Decimal(3),
    relative_tolerance: Decimal = Decimal("0.0001"),
) -> Workspace:
    """Timeline cells, ratios, changes, reconciliations and data-quality notes for a scope."""
    by_id = {s.fact.id: s for s in sources}
    periods = normalize_periods([s.fact for s in sources])
    latest: dict[uuid.UUID, str] = {}
    for s in sources:
        if s.fact.id in periods:
            label = periods[s.fact.id].label
            latest[s.document_id] = max(latest.get(s.document_id, label), label, key=_period_order)

    groups: dict[tuple[str, str], list[SourceFact]] = {}
    for s in sorted(sources, key=lambda s: str(s.fact.id)):
        if s.fact.id in periods:
            groups.setdefault((s.fact.metric, periods[s.fact.id].label), []).append(s)

    cells: dict[tuple[str, str], Cell] = {}
    resolved: list[FactInput] = []
    conflicted: list[FactInput] = []
    for (metric, period), group in sorted(groups.items()):
        accepted = [s for s in group if s.status == "accepted"]
        if not accepted:
            ids = [s.fact.id for s in group]
            cells[(metric, period)] = Cell(metric, period, "needs_review", ids, None)
            continue
        ids = [s.fact.id for s in accepted]
        if len({(s.fact.value, s.fact.currency) for s in accepted}) > 1:
            cells[(metric, period)] = Cell(metric, period, "conflict", ids, None)
            conflicted.append(accepted[0].fact)
            continue
        primary = _primary(accepted, period, latest)
        cells[(metric, period)] = Cell(metric, period, "value", ids, primary.fact.id)
        resolved.append(primary.fact)

    changes = year_over_year(resolved, conflicted)
    for cell in cells.values():
        if cell.primary_fact_id:
            f = by_id[cell.primary_fact_id].fact
            cell.change = changes.get((f.metric, f.period_type, f.period_label))

    # A ratio's period: FYn for annual ratios; for balance-sheet ratios, the normalized period of
    # its balance date (a fiscal year end, or the date itself).
    date_period = {
        by_id[i].fact.period_label: p.label
        for i, p in periods.items()
        if by_id[i].fact.period_type == "instant"
    }
    calculations = [
        (r.period_label if r.period_type == "annual" else date_period[r.period_label], r)
        for r in calculate(resolved, conflicted)
    ]

    ordered = sorted({p for _, p in cells}, key=_period_order)
    basis = {p.label: p.basis for p in periods.values()}
    reconciliations = []
    quality: list[QualityItem] = []
    for period in ordered:
        in_period = {m: c for (m, p), c in cells.items() if p == period}
        if any(m in in_period for m in ("total_assets", "total_liabilities", "equity")):
            rec = reconcile(period, in_period, by_id, rounding_units, relative_tolerance)
            reconciliations.append(rec)
            quality.append(_reconciliation_quality(rec))
        # Absent metrics show as gaps in the tables; listing every gap here would be noise.
        quality += [_cell_quality(in_period[m]) for m in TIMELINE_METRICS if m in in_period]

    return Workspace(
        periods=ordered,
        period_basis={p: basis[p] for p in ordered},
        cells=[cells[k] for k in sorted(cells, key=lambda k: (k[0], _period_order(k[1])))],
        calculations=calculations,
        reconciliations=reconciliations,
        quality=quality,
        fact_periods={i: p.label for i, p in periods.items()},
    )
