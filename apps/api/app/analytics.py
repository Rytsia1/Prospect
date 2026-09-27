"""Deterministic financial ratios from accepted facts (docs/FINANCIAL_CALCULATIONS.md).

Pure: no DB, no network, no LLM. Decimal only, in a fixed context, so the same facts always give
the same results. A missing input, a zero denominator, or inputs that do not fit together give a
not_possible result with a reason; nothing is ever substituted with zero or a nearby period.
Results are plain ratios at full precision; rounding happens only in the UI.
"""

import uuid
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from decimal import ROUND_HALF_EVEN, Context, Decimal
from typing import Literal

# Fixed context: independent of the process-global decimal context, so results are reproducible.
CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)

MISSING_INPUT = "MISSING_INPUT"
DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
INCOMPATIBLE_INPUTS = "INCOMPATIBLE_INPUTS"

Unit = Literal["percent", "times"]  # how to present the stored ratio: 0.18 → 18% or 0.18x

# formula_key → (metric, name, formula, unit)
FORMULAS: dict[str, tuple[str, str, str, Unit]] = {
    "revenue_growth": (
        "revenue_growth",
        "Revenue growth",
        "(revenue[FY] − revenue[FY−1]) / revenue[FY−1]",
        "percent",
    ),
    "net_margin": ("net_margin", "Net margin", "net_income[FY] / revenue[FY]", "percent"),
    "roa_average_assets": (
        "roa",
        "Return on assets (ROA)",
        "net_income[FY] / ((total_assets[start of FY] + total_assets[end of FY]) / 2)",
        "percent",
    ),
    "roa_ending_assets": (
        "roa",
        "Return on assets (ROA), ending assets",
        "net_income[FY] / total_assets[end of FY]",
        "percent",
    ),
    "roe_average_equity": (
        "roe",
        "Return on equity (ROE)",
        "net_income[FY] / ((equity[start of FY] + equity[end of FY]) / 2)",
        "percent",
    ),
    "roe_ending_equity": (
        "roe",
        "Return on equity (ROE), ending equity",
        "net_income[FY] / equity[end of FY]",
        "percent",
    ),
    "debt_to_equity": ("debt_to_equity", "Debt-to-equity", "total_debt / equity", "times"),
    "current_ratio": (
        "current_ratio",
        "Current ratio",
        "current_assets / current_liabilities",
        "times",
    ),
}
METRIC_ORDER = ["revenue_growth", "net_margin", "roa", "roe", "debt_to_equity", "current_ratio"]
# Input facts listed numerator first, so "Based on ..." reads in formula order.
INPUT_ORDER = [
    "net_income",
    "revenue",
    "total_debt",
    "current_assets",
    "current_liabilities",
    "total_assets",
    "equity",
]
_NAMES = {  # input descriptions used in reasons
    "total_assets": "Total assets",
    "equity": "Total equity",
    "total_debt": "Total debt",
    "current_assets": "Total current assets",
    "current_liabilities": "Total current liabilities",
}


@dataclass(frozen=True)
class FactInput:
    """An accepted financial fact; value is the full amount in currency units."""

    id: uuid.UUID
    metric: str
    value: Decimal
    currency: str
    period_type: str
    period_label: str
    period_end: date | None
    fiscal_year: int | None


@dataclass(frozen=True)
class Result:
    metric: str
    formula_key: str
    period_type: str
    period_label: str
    status: Literal["calculated", "not_possible"]
    value: Decimal | None  # plain ratio, full precision; None unless calculated
    unit: Unit
    input_ids: tuple[uuid.UUID, ...]  # the facts used (or those found, when not possible)
    reason_code: str | None = None
    reason: str | None = None
    notes: tuple[str, ...] = ()


# (description used in reasons, the fact or None when not found), in formula argument order
Needed = list[tuple[str, FactInput | None]]


def evaluate(
    formula_key: str,
    period_type: str,
    period_label: str,
    needed: Needed,
    fraction: Callable[..., tuple[Decimal, Decimal]],
    incompatible: str | None = None,
    notes: tuple[str, ...] = (),
) -> Result:
    """Check inputs, then divide. `fraction` maps input values to (numerator, denominator)."""
    metric, _, _, unit = FORMULAS[formula_key]
    found = [f for _, f in needed if f is not None]
    base = Result(
        metric,
        formula_key,
        period_type,
        period_label,
        "not_possible",
        None,
        unit,
        tuple(f.id for f in found),
        notes=notes,
    )

    def not_possible(code: str, reason: str) -> Result:
        return replace(base, reason_code=code, reason=reason)

    missing = [desc for desc, f in needed if f is None]
    if missing:
        return not_possible(MISSING_INPUT, "; ".join(f"{m} was not found" for m in missing) + ".")
    currencies = sorted({f.currency for f in found})
    if len(currencies) > 1:
        return not_possible(
            INCOMPATIBLE_INPUTS, f"Inputs are in different currencies ({', '.join(currencies)})."
        )
    if incompatible:
        return not_possible(INCOMPATIBLE_INPUTS, incompatible)
    numerator, denominator = fraction(*(f.value for f in found))
    if denominator == 0:
        return not_possible(DIVISION_BY_ZERO, "The denominator is zero, so the ratio is undefined.")
    if denominator < 0:
        notes += ("The denominator is negative, so this ratio does not have its usual meaning.",)
    value = CONTEXT.divide(numerator, denominator)
    return replace(base, status="calculated", value=value, notes=notes)


def _year_before(end: date) -> date:
    try:
        return end.replace(year=end.year - 1)
    except ValueError:  # 29 February
        return date(end.year - 1, 2, 28)


def _average(a: Decimal, b: Decimal) -> Decimal:
    return CONTEXT.divide(CONTEXT.add(a, b), Decimal(2))


def _revenue_periods_problem(
    year: int, current: FactInput | None, previous: FactInput | None
) -> str | None:
    """Growth needs two comparable annual periods exactly a year apart."""
    if not (current and previous):
        return None  # reported as missing instead
    if (current.period_end is None) != (previous.period_end is None):
        return f"FY{year} and FY{year - 1} revenue do not state comparable periods."
    if current.period_end and _year_before(current.period_end) != previous.period_end:
        return f"FY{year} and FY{year - 1} revenue periods are not a year apart."
    return None


def _returns(
    year: int, net_income: FactInput | None, instants: dict[tuple[str, object], FactInput]
) -> list[Result]:
    """ROA and ROE on average balances; a labeled ending-balance variant if the start is missing."""
    label = f"FY{year}"
    # Balances at the end and start of the year, anchored on the income fact's end date.
    end: date | int = net_income.period_end if net_income and net_income.period_end else year
    start: date | int = _year_before(end) if isinstance(end, date) else year - 1
    end_text = end.isoformat() if isinstance(end, date) else f"end of FY{end}"
    start_text = start.isoformat() if isinstance(start, date) else f"end of FY{start}"
    ni = (f"Net income for {label}", net_income)
    results = []
    for metric, average_key, ending_key in (
        ("total_assets", "roa_average_assets", "roa_ending_assets"),
        ("equity", "roe_average_equity", "roe_ending_equity"),
    ):
        name = _NAMES[metric]
        ending, beginning = instants.get((metric, end)), instants.get((metric, start))
        if beginning is None and ending is not None:
            # Clearly labeled as a different formula, never silently substituted for the average.
            note = (
                f"{name} at {start_text} was not found, so this uses {name.lower()} at "
                f"{end_text} instead of the average."
            )
            results.append(
                evaluate(
                    ending_key,
                    "annual",
                    label,
                    [ni, (f"{name} at {end_text}", ending)],
                    lambda n, e: (n, e),
                    notes=(note,),
                )
            )
            continue
        results.append(
            evaluate(
                average_key,
                "annual",
                label,
                [ni, (f"{name} at {start_text}", beginning), (f"{name} at {end_text}", ending)],
                lambda n, s, e: (n, _average(s, e)),
            )
        )
    return results


def calculate(facts: list[FactInput]) -> list[Result]:
    """Every supported ratio for every annual year and balance-sheet date found in the facts.

    `facts` must be accepted facts: at most one per (metric, period_type, period_label).
    """
    # Input order never changes the result (and ties on a balance date resolve the same way).
    facts = sorted(facts, key=lambda f: (f.metric, f.period_label, str(f.id)))
    annual = {(f.metric, f.fiscal_year): f for f in facts if f.period_type == "annual"}
    # Balances are keyed by their date, or by fiscal year when the document states only the year.
    instants: dict[tuple[str, object], FactInput] = {
        (f.metric, f.period_end or f.fiscal_year): f for f in facts if f.period_type == "instant"
    }
    results: list[Result] = []

    for year in sorted({y for _, y in annual if y is not None}):
        label = f"FY{year}"
        revenue, net_income = annual.get(("revenue", year)), annual.get(("net_income", year))
        previous = annual.get(("revenue", year - 1))
        results.append(
            evaluate(
                "revenue_growth",
                "annual",
                label,
                [(f"Revenue for FY{year - 1}", previous), (f"Revenue for {label}", revenue)],
                lambda prev, cur: (CONTEXT.subtract(cur, prev), prev),
                _revenue_periods_problem(year, revenue, previous),
            )
        )
        results.append(
            evaluate(
                "net_margin",
                "annual",
                label,
                [(f"Net income for {label}", net_income), (f"Revenue for {label}", revenue)],
                lambda n, r: (n, r),
            )
        )
        results += _returns(year, net_income, instants)

    labels = {key: f.period_label for (_, key), f in instants.items()}
    for key in sorted(labels, key=str):
        at = f"at {labels[key]}" if isinstance(key, date) else f"at end of {labels[key]}"
        for formula_key, num, den in (
            ("debt_to_equity", "total_debt", "equity"),
            ("current_ratio", "current_assets", "current_liabilities"),
        ):
            results.append(
                evaluate(
                    formula_key,
                    "instant",
                    labels[key],
                    [
                        (f"{_NAMES[num]} {at}", instants.get((num, key))),
                        (f"{_NAMES[den]} {at}", instants.get((den, key))),
                    ],
                    lambda n, d: (n, d),
                )
            )

    return sorted(results, key=lambda r: (METRIC_ORDER.index(r.metric), r.period_label))
