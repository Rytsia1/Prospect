"""Formula tests for app/analytics.py: pure, no database."""

import random
import uuid
from datetime import date
from decimal import Decimal, localcontext

import pytest

from app.analytics import (
    DIVISION_BY_ZERO,
    INCOMPATIBLE_INPUTS,
    MISSING_INPUT,
    FactInput,
    Result,
    calculate,
    year_over_year,
)

T = Decimal(10) ** 12
FY2025, FY2024 = date(2025, 12, 31), date(2024, 12, 31)


def fact(metric: str, value, period, currency: str = "IDR") -> FactInput:
    """period: an int fiscal year (annual, ending 31 Dec) or a date (balance-sheet instant)."""
    value = Decimal(value)
    if isinstance(period, int):
        end = date(period, 12, 31)
        return FactInput(
            uuid.uuid4(), metric, value, currency, "annual", f"FY{period}", end, period
        )
    label = period.isoformat()
    return FactInput(uuid.uuid4(), metric, value, currency, "instant", label, period, period.year)


def raw(metric: str, value, period_type: str, label: str, end: date | None, year: int):
    return FactInput(uuid.uuid4(), metric, Decimal(value), "IDR", period_type, label, end, year)


def one(facts: list[FactInput], metric: str, period_label: str) -> Result:
    [result] = [r for r in calculate(facts) if (r.metric, r.period_label) == (metric, period_label)]
    return result


def ids(*facts: FactInput) -> set[uuid.UUID]:
    return {f.id for f in facts}


# --- Revenue growth ------------------------------------------------------------------------


def test_revenue_growth():
    prev, cur = fact("revenue", 10_500 * 10**9, 2024), fact("revenue", 12_400 * 10**9, 2025)
    r = one([prev, cur], "revenue_growth", "FY2025")
    assert (r.status, r.formula_key, r.unit) == ("calculated", "revenue_growth", "percent")
    assert r.value == Decimal("0.1809523809523809523809523809523810")
    assert set(r.input_ids) == ids(prev, cur)


def test_revenue_decline_is_negative():
    r = one([fact("revenue", 100, 2024), fact("revenue", 75, 2025)], "revenue_growth", "FY2025")
    assert r.value == Decimal("-0.25")


def test_revenue_growth_zero_previous_revenue_is_not_possible():
    r = one([fact("revenue", 0, 2024), fact("revenue", 75, 2025)], "revenue_growth", "FY2025")
    assert (r.status, r.value, r.reason_code) == ("not_possible", None, DIVISION_BY_ZERO)


def test_revenue_growth_missing_previous_year():
    cur = fact("revenue", 75, 2025)
    r = one([cur], "revenue_growth", "FY2025")
    assert (r.status, r.value, r.reason_code) == ("not_possible", None, MISSING_INPUT)
    assert r.reason == "Revenue for FY2024 was not found."
    assert set(r.input_ids) == ids(cur)  # what was found stays inspectable


def test_revenue_growth_from_negative_base_is_flagged():
    r = one([fact("revenue", -100, 2024), fact("revenue", 50, 2025)], "revenue_growth", "FY2025")
    assert r.value == Decimal("-1.5")  # the arithmetic is kept; its meaning is flagged
    assert "negative" in r.notes[0]


def test_revenue_growth_needs_periods_a_year_apart():
    # The fiscal year end changed: FY2024 ended in June, FY2025 in December.
    prev = raw("revenue", 100, "annual", "FY2024", date(2024, 6, 30), 2024)
    r = one([prev, fact("revenue", 120, 2025)], "revenue_growth", "FY2025")
    assert (r.status, r.reason_code) == ("not_possible", INCOMPATIBLE_INPUTS)


def test_quarterly_revenue_is_never_used_as_annual():
    quarter = raw("revenue", 30, "quarter", "Q4 2024", None, 2024)
    r = one([quarter, fact("revenue", 120, 2025)], "revenue_growth", "FY2025")
    assert (r.status, r.reason_code) == ("not_possible", MISSING_INPUT)


# --- Net margin ----------------------------------------------------------------------------


def test_net_margin():
    r = one([fact("net_income", 1740, 2025), fact("revenue", 12400, 2025)], "net_margin", "FY2025")
    assert r.value == Decimal("0.1403225806451612903225806451612903")


def test_net_margin_of_a_net_loss_is_negative():
    r = one([fact("net_income", -250, 2025), fact("revenue", 1000, 2025)], "net_margin", "FY2025")
    assert (r.status, r.value, r.notes) == ("calculated", Decimal("-0.25"), ())


def test_net_margin_zero_revenue():
    r = one([fact("net_income", 5, 2025), fact("revenue", 0, 2025)], "net_margin", "FY2025")
    assert (r.status, r.reason_code) == ("not_possible", DIVISION_BY_ZERO)


def test_net_margin_missing_net_income():
    r = one([fact("revenue", 1000, 2025)], "net_margin", "FY2025")
    assert (r.status, r.reason) == ("not_possible", "Net income for FY2025 was not found.")


def test_net_margin_mixed_currencies_is_not_possible():
    facts = [fact("net_income", 5, 2025, "USD"), fact("revenue", 100, 2025, "IDR")]
    r = one(facts, "net_margin", "FY2025")
    assert (r.status, r.reason_code) == ("not_possible", INCOMPATIBLE_INPUTS)
    assert r.reason and "IDR, USD" in r.reason


# --- ROA / ROE -----------------------------------------------------------------------------


def test_roa_uses_average_assets():
    ni = fact("net_income", Decimal("1.74") * T, 2025)
    start = fact("total_assets", Decimal("41.2") * T, FY2024)
    end = fact("total_assets", Decimal("45.6") * T, FY2025)
    r = one([ni, start, end], "roa", "FY2025")
    assert r.formula_key == "roa_average_assets"
    assert r.value == Decimal("0.04009216589861751152073732718894009")  # 1.74 / 43.4
    assert set(r.input_ids) == ids(ni, start, end)


def test_roa_without_opening_assets_is_a_labeled_ending_variant():
    r = one([fact("net_income", 10, 2025), fact("total_assets", 200, FY2025)], "roa", "FY2025")
    assert (r.status, r.formula_key, r.value) == (
        "calculated",
        "roa_ending_assets",
        Decimal("0.05"),
    )
    assert "2024-12-31 was not found" in r.notes[0]


def test_roa_without_any_assets_is_not_possible():
    r = one([fact("net_income", 10, 2025)], "roa", "FY2025")
    assert (r.status, r.formula_key, r.reason_code) == (
        "not_possible",
        "roa_average_assets",
        MISSING_INPUT,
    )
    assert r.reason and "Total assets at 2024-12-31" in r.reason
    assert "Total assets at 2025-12-31" in r.reason


def test_roa_zero_assets():
    facts = [
        fact("net_income", 10, 2025),
        fact("total_assets", 0, FY2024),
        fact("total_assets", 0, FY2025),
    ]
    assert one(facts, "roa", "FY2025").reason_code == DIVISION_BY_ZERO


def test_roe_missing_equity():
    r = one([fact("net_income", 10, 2025)], "roe", "FY2025")
    assert r.status == "not_possible" and r.value is None
    assert r.reason and "Total equity at 2025-12-31 was not found" in r.reason


def test_roe_average_equity():
    facts = [fact("net_income", 15, 2025), fact("equity", 100, FY2024), fact("equity", 200, FY2025)]
    assert one(facts, "roe", "FY2025").value == Decimal("0.1")


def test_roe_with_net_loss_and_negative_equity():
    facts = [
        fact("net_income", -30, 2025),
        fact("equity", -100, FY2024),
        fact("equity", -200, FY2025),
    ]
    r = one(facts, "roe", "FY2025")
    assert r.value == Decimal("0.2")  # a loss over negative equity looks positive...
    assert "negative" in r.notes[0]  # ...so it is flagged


def test_year_only_balance_sheet_matches_year_only_income_statement():
    facts = [
        raw("net_income", 10, "annual", "FY2025", None, 2025),
        raw("total_assets", 100, "instant", "FY2024", None, 2024),
        raw("total_assets", 300, "instant", "FY2025", None, 2025),
    ]
    r = one(facts, "roa", "FY2025")
    assert (r.formula_key, r.value) == ("roa_average_assets", Decimal("0.05"))


# --- Debt-to-equity / current ratio --------------------------------------------------------


def test_debt_to_equity():
    facts = [
        fact("total_debt", Decimal("8.3") * T, FY2025),
        fact("equity", Decimal("25.5") * T, FY2025),
    ]
    r = one(facts, "debt_to_equity", "2025-12-31")
    assert (r.unit, r.value) == ("times", Decimal("0.3254901960784313725490196078431373"))


def test_debt_to_equity_zero_and_negative_equity():
    zero = [fact("total_debt", 10, FY2025), fact("equity", 0, FY2025)]
    assert one(zero, "debt_to_equity", "2025-12-31").reason_code == DIVISION_BY_ZERO
    negative = [fact("total_debt", 10, FY2025), fact("equity", -5, FY2025)]
    r = one(negative, "debt_to_equity", "2025-12-31")
    assert r.value == Decimal(-2) and "negative" in r.notes[0]


def test_debt_to_equity_does_not_mix_balance_sheet_dates():
    facts = [fact("total_debt", 10, FY2024), fact("equity", 5, FY2025)]
    for label in ("2024-12-31", "2025-12-31"):
        assert one(facts, "debt_to_equity", label).reason_code == MISSING_INPUT


def test_current_ratio():
    facts = [
        fact("current_assets", 12_450_000, FY2025),
        fact("current_liabilities", 9_960_000, FY2025),
    ]
    assert one(facts, "current_ratio", "2025-12-31").value == Decimal("1.25")


def test_current_ratio_zero_and_missing():
    facts = [fact("current_assets", 5, FY2025), fact("current_liabilities", 0, FY2025)]
    assert one(facts, "current_ratio", "2025-12-31").reason_code == DIVISION_BY_ZERO
    r = one([fact("current_assets", 5, FY2025)], "current_ratio", "2025-12-31")
    assert r.reason == "Total current liabilities at 2025-12-31 was not found."


# --- Precision and determinism -------------------------------------------------------------


def test_precision_beyond_float():
    # 2^53 + 1 is not representable as a float; Decimal keeps the difference.
    big = 2**53
    assert float(big + 1) == float(big)
    facts = [fact("revenue", big, 2024), fact("revenue", big + 1, 2025)]
    r = one(facts, "revenue_growth", "FY2025")
    assert r.value == Decimal("1.110223024625156540423631668090820E-16")


def test_high_precision_fractional_amounts():
    facts = [
        fact("net_income", "123456789012345.67", 2025),
        fact("revenue", "987654321098765.43", 2025),
    ]
    r = one(facts, "net_margin", "FY2025")
    assert r.value == Decimal("0.1249999988609374912687695298117556")  # 34 significant digits
    assert r.value is not None and len(r.value.as_tuple().digits) == 34  # full precision kept


def test_same_facts_same_results_regardless_of_order_or_global_context():
    facts = [
        fact("revenue", 10_500, 2024),
        fact("revenue", 12_400, 2025),
        fact("net_income", 1_400, 2024),
        fact("net_income", 1_740, 2025),
        fact("total_assets", 41_200, FY2024),
        fact("total_assets", 45_600, FY2025),
        fact("equity", 21_900, FY2024),
        fact("equity", 25_500, FY2025),
        fact("total_debt", 9_100, FY2024),
        fact("total_debt", 8_300, FY2025),
    ]
    expected = calculate(facts)
    shuffled = facts[:]
    random.Random(7).shuffle(shuffled)
    with localcontext() as ctx:
        ctx.prec = 3  # a caller changing the global context must not change results
        assert calculate(shuffled) == expected
    assert [(r.metric, r.period_label) for r in expected][:4] == [
        ("revenue_growth", "FY2024"),
        ("revenue_growth", "FY2025"),
        ("net_margin", "FY2024"),
        ("net_margin", "FY2025"),
    ]


def test_no_facts_no_calculations():
    assert calculate([]) == []


@pytest.mark.parametrize("value", ["0", "0.00"])
def test_a_reported_zero_is_a_value_not_a_missing_input(value):
    facts = [fact("net_income", value, 2025), fact("revenue", 100, 2025)]
    assert one(facts, "net_margin", "FY2025").value == 0


def test_conflicting_opening_balance_is_not_replaced_by_the_ending_variant():
    ni, end = fact("net_income", 10, 2025), fact("total_assets", 200, FY2025)
    disputed = fact("total_assets", 150, FY2024)
    r = one_of(calculate([ni, end], conflicted=[disputed]), "roa", "FY2025")
    assert (r.status, r.formula_key, r.reason_code) == (
        "not_possible",
        "roa_average_assets",
        INCOMPATIBLE_INPUTS,
    )


def test_year_over_year_for_flows_and_balances():
    changes = year_over_year(
        [
            fact("net_income", 100, 2024),
            fact("net_income", 80, 2025),
            fact("equity", 50, FY2024),
            fact("equity", 60, FY2025),
        ]
    )
    assert changes[("net_income", "annual", "FY2025")].value == Decimal("-0.2")
    assert changes[("equity", "instant", "2025-12-31")].value == Decimal("0.2")
    assert ("net_income", "annual", "FY2024") not in changes  # no earlier year: no change


def test_negative_numerator_and_denominator_is_flagged():
    # Net loss with negative equity: mathematical division is positive, but performance is negative
    loss = fact("net_income", -10, 2025)
    def_eq = fact("equity", -50, FY2025)
    r = one_of(calculate([loss, def_eq]), "roe", "FY2025")
    assert r.status == "calculated"
    assert r.value == Decimal("0.2")  # (-10) / (-50) = +0.20
    assert len(r.notes) >= 1
    assert any("does not represent a positive financial return" in n for n in r.notes)


def one_of(results, metric, period_label):
    [r] = [r for r in results if (r.metric, r.period_label) == (metric, period_label)]
    return r
