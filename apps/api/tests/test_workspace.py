"""Timeline merging, period normalization, reconciliation and data quality (app/workspace.py)."""

import uuid
from datetime import date
from decimal import Decimal

from app.analytics import INCOMPATIBLE_INPUTS, FactInput
from app.workspace import SourceFact, build, normalize_periods

AR2024, AR2025 = uuid.uuid4(), uuid.uuid4()
D24, D25 = date(2024, 12, 31), date(2025, 12, 31)


def src(metric, value, period, doc=AR2025, status="accepted", scale="millions", currency="IDR"):
    """period: int fiscal year (annual, ending 31 Dec) or a date (balance sheet)."""
    if isinstance(period, int):
        label, end, year, kind = f"FY{period}", date(period, 12, 31), period, "annual"
    else:
        label, end, year, kind = period.isoformat(), period, period.year, "instant"
    fact = FactInput(uuid.uuid4(), metric, Decimal(value), currency, kind, label, end, year)
    return SourceFact(fact, doc, status, scale)


def raw(metric, value, kind, label, end, year):
    return FactInput(uuid.uuid4(), metric, Decimal(value), "IDR", kind, label, end, year)


def cell(ws, metric, period):
    [c] = [c for c in ws.cells if (c.metric, c.period) == (metric, period)]
    return c


def calc(ws, metric, period):
    [r] = [r for p, r in ws.calculations if (r.metric, p) == (metric, period)]
    return r


# --- Periods ------------------------------------------------------------------------------


def test_multiple_periods_oldest_first_across_documents():
    ws = build(
        [
            src("revenue", 12_400, 2025),
            src("revenue", 10_500, 2024),
            src("revenue", 9_000, 2023, doc=AR2024),
        ]
    )
    assert ws.periods == ["FY2023", "FY2024", "FY2025"]


def test_balance_dates_become_fiscal_years_only_when_an_annual_period_ends_there():
    ni = src("net_income", 10, 2025).fact
    june = raw("total_assets", 1, "instant", "2025-06-30", date(2025, 6, 30), 2025)
    dec = src("total_assets", 1, D25).fact
    periods = normalize_periods([ni, june, dec])
    assert (periods[dec.id].label, periods[dec.id].basis) == ("FY2025", "fiscal_year_end")
    # Nothing establishes that 30 June 2025 closes a fiscal year: the date is kept as is.
    assert (periods[june.id].label, periods[june.id].basis) == ("2025-06-30", "date")


def test_a_non_calendar_fiscal_year_is_respected():
    fy = raw("net_income", 10, "annual", "FY2025", date(2025, 3, 31), 2025)
    march = raw("total_assets", 1, "instant", "2025-03-31", date(2025, 3, 31), 2025)
    december = src("total_assets", 1, D24).fact
    periods = normalize_periods([fy, march, december])
    assert periods[march.id].label == "FY2025"
    assert periods[december.id].label == "2024-12-31"  # never assumed to be FY2024


def test_quarters_are_not_mixed_into_the_annual_timeline():
    quarter = raw("revenue", 3, "quarter", "Q4 2025", None, 2025)
    ws = build([SourceFact(quarter, AR2025, "accepted", "millions"), src("revenue", 12, 2025)])
    assert ws.periods == ["FY2025"]
    assert quarter.id not in cell(ws, "revenue", "FY2025").fact_ids


def test_missing_periods_are_gaps_not_zeros():
    ws = build([src("revenue", 12, 2025), src("net_income", 1, 2024)])
    assert ws.periods == ["FY2024", "FY2025"]
    assert not [c for c in ws.cells if (c.metric, c.period) == ("revenue", "FY2024")]


# --- Duplicates and conflicts -------------------------------------------------------------


def test_comparative_that_agrees_is_one_value_from_the_reports_own_year():
    own = src("revenue", 10_500, 2024, doc=AR2024)
    comparative = src("revenue", 10_500, 2024, doc=AR2025)
    ws = build(
        [own, comparative, src("revenue", 12_400, 2025), src("revenue", 9_000, 2023, doc=AR2024)]
    )
    c = cell(ws, "revenue", "FY2024")
    assert c.status == "value"
    assert set(c.fact_ids) == {own.fact.id, comparative.fact.id}
    assert c.primary_fact_id == own.fact.id  # the 2024 report is the authority for FY2024
    assert any("agreed by 2 sources" in q.message for q in ws.quality)


def test_conflicting_values_are_kept_and_block_dependent_calculations():
    a = src("revenue", 10_800, 2024, doc=AR2024)
    b = src("revenue", 10_820, 2024, doc=AR2025)
    ws = build([a, b, src("revenue", 12_400, 2025)])
    c = cell(ws, "revenue", "FY2024")
    assert (c.status, c.primary_fact_id) == ("conflict", None)
    assert set(c.fact_ids) == {a.fact.id, b.fact.id}  # nothing discarded
    growth = calc(ws, "revenue_growth", "FY2025")
    assert (growth.status, growth.reason_code) == ("not_possible", INCOMPATIBLE_INPUTS)
    assert "conflicting values" in (growth.reason or "")
    change = cell(ws, "revenue", "FY2025").change
    assert change is not None and change.reason_code == INCOMPATIBLE_INPUTS
    assert any(q.level == "warning" and "conflicting" in q.message for q in ws.quality)


def test_needs_review_values_are_never_shown_as_values():
    review = src("total_debt", -5, D25, status="needs_review")
    ws = build([review, src("net_income", 1, 2025)])
    c = cell(ws, "total_debt", "FY2025")
    assert (c.status, c.primary_fact_id, c.fact_ids) == ("needs_review", None, [review.fact.id])
    assert any(q.message == "Total debt value requires review" for q in ws.quality)


def test_same_facts_same_workspace_regardless_of_order():
    facts = [
        src("revenue", 10_500, 2024, doc=AR2024),
        src("revenue", 10_500, 2024),
        src("revenue", 12_400, 2025),
        src("total_assets", 45, D25),
        src("equity", 25, D25),
    ]
    first, again = build(facts), build(list(reversed(facts)))
    assert [(c.metric, c.period, c.primary_fact_id) for c in first.cells] == [
        (c.metric, c.period, c.primary_fact_id) for c in again.cells
    ]
    assert first.calculations == again.calculations


# --- Changes (from the calculation engine) ------------------------------------------------


def test_year_over_year_changes_come_from_the_engine():
    ws = build(
        [
            src("revenue", 10_500, 2024),
            src("revenue", 12_400, 2025),
            src("total_assets", 40, D24),
            src("total_assets", 50, D25),
        ]
    )
    revenue = cell(ws, "revenue", "FY2025").change
    assert revenue is not None
    assert revenue.value == Decimal("0.1809523809523809523809523809523810")
    assets = cell(ws, "total_assets", "FY2025").change
    assert assets is not None and assets.value == Decimal("0.25")
    assert cell(ws, "revenue", "FY2024").change is None  # no FY2023: no change shown


def test_change_from_a_negative_base_is_flagged():
    ws = build([src("net_income", -100, 2024), src("net_income", 50, 2025)])
    change = cell(ws, "net_income", "FY2025").change
    assert change is not None and change.value == Decimal("-1.5")
    assert "negative" in change.notes[0]


def test_balance_ratio_periods_are_normalized():
    ws = build([src("net_income", 1, 2025), src("total_debt", 10, D25), src("equity", 20, D25)])
    assert calc(ws, "debt_to_equity", "FY2025").value == Decimal("0.5")


# --- Reconciliation -----------------------------------------------------------------------


def balance(assets, liabilities, equity, **kw):
    return build(
        [
            src("net_income", 1, 2025),
            src("total_assets", assets, D25, **kw),
            src("total_liabilities", liabilities, D25, **kw),
            src("equity", equity, D25, **kw),
        ]
    ).reconciliations


def test_balanced():
    [rec] = balance(45_600_000_000_000, 20_100_000_000_000, 25_500_000_000_000)
    assert (rec.status, rec.difference, rec.period) == ("BALANCED", 0, "FY2025")
    assert set(rec.fact_ids) == {"total_assets", "total_liabilities", "equity"}


def test_rounding_difference_within_printed_units():
    # Printed in millions: 1 million off is rounding (tolerance: 3 printed units = 3 million).
    [rec] = balance(45_600_001_000_000, 20_100_000_000_000, 25_500_000_000_000)
    assert (rec.status, rec.difference) == ("ROUNDING_DIFFERENCE", Decimal(1_000_000))
    assert rec.tolerance == Decimal(3_000_000)


def test_material_mismatch():
    [rec] = balance(45_600_000_000_000, 20_100_000_000_000, 25_000_000_000_000)
    assert (rec.status, rec.difference) == ("MISMATCH", Decimal(500_000_000_000))


def test_coarse_scale_cannot_hide_a_material_gap():
    # Printed in trillions, 3 units would be Rp3T; the relative cap (0.01% of assets) keeps the
    # tolerance at Rp4.56B, so a Rp1T gap is still a mismatch.
    [rec] = balance(45_600_000_000_000, 20_100_000_000_000, 24_500_000_000_000, scale="trillions")
    assert rec.status == "MISMATCH" and rec.tolerance == Decimal("4560000000")


def test_missing_input_is_insufficient_data_not_zero():
    [rec] = build(
        [
            src("net_income", 1, 2025),
            src("total_assets", 45, D25),
            src("total_liabilities", 20, D25),
        ]
    ).reconciliations
    assert (rec.status, rec.difference) == ("INSUFFICIENT_DATA", None)
    assert rec.problems == ["Missing: Total equity — FY2025"]


def test_zero_values_are_values():
    [rec] = balance(0, 0, 0)
    assert rec.status == "BALANCED"
    [rec] = balance(0, 10, 0)
    assert rec.status == "MISMATCH"


def test_conflicted_or_review_inputs_cannot_reconcile():
    ws = build(
        [
            src("net_income", 1, 2025),
            src("total_assets", 45, D25, doc=AR2024),
            src("total_assets", 46, D25),
            src("total_liabilities", 20, D25),
            src("equity", -1, D25, status="needs_review"),
        ]
    )
    [rec] = ws.reconciliations
    assert rec.status == "INSUFFICIENT_DATA"
    assert "Total assets — FY2025 has conflicting values across documents" in rec.problems
    assert "Missing: Total equity — FY2025 (a value was found but needs review)" in rec.problems


def test_mixed_currencies_cannot_reconcile():
    ws = build(
        [
            src("total_assets", 45, D25),
            src("total_liabilities", 20, D25),
            src("equity", 25, D25, currency="USD"),
        ]
    )
    [rec] = ws.reconciliations
    assert rec.status == "INSUFFICIENT_DATA" and "different currencies" in rec.problems[0]
