"""Financial fact extraction: numbers, units, periods, validation, evidence. Pure: no DB."""

from datetime import date
from decimal import Decimal

import pytest
from sample_pdf import build_sample_report

from app.extraction import (
    AmountError,
    Header,
    extract_facts,
    header_line,
    match_metric,
    parse_amount,
    parse_header,
    resolve_period,
    unit_statement,
)
from app.processing import Block, ParsedPage, chunk_pages, detect_sections, parse_pdf

T = Decimal(10) ** 12


def page(number: int, *blocks: tuple[str, str], heading: str | None = None) -> ParsedPage:
    """A synthetic parsed page. Blocks are (kind, text); an optional heading block goes first."""
    items = ([("heading", heading)] if heading else []) + list(blocks)
    return ParsedPage(
        number,
        [
            Block(i, "text" if k == "heading" else k, (0, 0, 1, 1), text, 10, False, k == "heading")  # type: ignore[arg-type]
            for i, (k, text) in enumerate(items)
        ],
        "success",
        {},
    )


def run(*pages: ParsedPage):
    sections, assignment = detect_sections(list(pages))
    chunks = chunk_pages(list(pages), assignment)
    return extract_facts(list(pages), sections, assignment, chunks)


def accepted(facts) -> dict[tuple[str, str], Decimal]:
    return {
        (f.candidate.metric, f.candidate.period.label): f.candidate.amount.value
        for f in facts
        if f.status == "accepted"
    }


INCOME = "Consolidated Statement of Profit or Loss"
BALANCE = "Consolidated Statement of Financial Position"


# --- End to end on the sample report: every initial metric -------------------------------


@pytest.fixture(scope="module")
def sample_facts(tmp_path_factory):
    pages = parse_pdf(build_sample_report(tmp_path_factory.mktemp("pdf") / "report.pdf"))
    return run(*pages)


def test_all_initial_metrics_are_extracted_with_page_provenance(sample_facts):
    facts, rejections = sample_facts
    values = accepted(facts)
    assert values == {
        ("revenue", "FY2025"): Decimal("12.4") * T,
        ("revenue", "FY2024"): Decimal("10.5") * T,
        ("gross_profit", "FY2025"): Decimal("4.96") * T,
        ("gross_profit", "FY2024"): Decimal("4.1") * T,
        ("operating_income", "FY2025"): Decimal("2.48") * T,
        ("operating_income", "FY2024"): Decimal("2.05") * T,
        ("net_income", "FY2025"): Decimal("1.74") * T,
        ("net_income", "FY2024"): Decimal("1.4") * T,
        ("cash", "2025-12-31"): Decimal("3.1205") * T,
        ("cash", "2024-12-31"): Decimal("2.84025") * T,
        ("current_assets", "2025-12-31"): Decimal("12.45") * T,
        ("current_assets", "2024-12-31"): Decimal("11.3") * T,
        ("current_liabilities", "2025-12-31"): Decimal("9.96") * T,
        ("current_liabilities", "2024-12-31"): Decimal("9.04") * T,
        ("total_assets", "2025-12-31"): Decimal("45.6") * T,
        ("total_assets", "2024-12-31"): Decimal("41.2") * T,
        ("total_debt", "2025-12-31"): Decimal("8.3") * T,
        ("total_debt", "2024-12-31"): Decimal("9.1") * T,
        ("total_liabilities", "2025-12-31"): Decimal("20.1") * T,
        ("total_liabilities", "2024-12-31"): Decimal("19.3") * T,
        ("equity", "2025-12-31"): Decimal("25.5") * T,
        ("equity", "2024-12-31"): Decimal("21.9") * T,
    }
    assert rejections == []
    for f in facts:
        c = f.candidate
        assert c.amount.currency == "IDR"
        expected_page = 2 if c.period.type == "annual" else 5
        assert c.page_number == expected_page
        assert c.source_text.startswith(match_label(c.metric))


def match_label(metric: str) -> str:
    return {
        "revenue": "Revenue",
        "gross_profit": "Gross profit",
        "operating_income": "Operating income",
        "net_income": "Net income",
        "cash": "Cash and cash equivalents",
        "total_assets": "Total assets",
        "current_assets": "Total current assets",
        "current_liabilities": "Total current liabilities",
        "total_debt": "Total borrowings",
        "total_liabilities": "Total liabilities",
        "equity": "Total equity",
    }[metric]


def test_periods_distinguish_fiscal_years_and_balance_sheet_dates(sample_facts):
    facts, _ = sample_facts
    by_key = {(f.candidate.metric, f.candidate.period.label): f.candidate.period for f in facts}
    income = by_key[("revenue", "FY2025")]
    assert (income.type, income.end, income.fiscal_year) == ("annual", date(2025, 12, 31), 2025)
    balance = by_key[("total_assets", "2025-12-31")]
    assert (balance.type, balance.end) == ("instant", date(2025, 12, 31))


def test_original_text_and_units_are_preserved(sample_facts):
    facts, _ = sample_facts
    cash = next(
        f for f in facts if f.candidate.metric == "cash" and f.candidate.period.fiscal_year == 2025
    )
    assert cash.candidate.amount.original_text == "3.120.500"
    assert cash.candidate.amount.scale == "millions"
    assert "millions of Rupiah" in (cash.candidate.unit_text or "")
    revenue = next(f for f in facts if f.candidate.metric == "revenue")
    assert revenue.candidate.amount.scale == "billions"
    assert revenue.candidate.unit_text == "(Rp billion)"


def test_look_alike_rows_are_not_metrics(sample_facts):
    facts, _ = sample_facts
    sources = {f.candidate.source_text for f in facts}
    assert not any(s.startswith("Total liabilities and equity") for s in sources)
    assert not any(s.startswith("Retained earnings") for s in sources)


# --- Numbers -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    ["Rp 1.740.000.000.000", "1,740,000,000,000", "1.74 trillion", "1.74 T", "Rp1.74T", "1,740 bn"],
)
def test_number_formats_normalize_to_the_same_value(text):
    assert parse_amount(text).value == Decimal("1740000000000")  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("(1,250)", "-1250"), ("-1,250", "-1250"), ("−1,250", "-1250"), ("Rp -1.250.000", "-1250000")],
)
def test_negative_values_stay_negative(text, expected):
    assert parse_amount(text).value == Decimal(expected)  # type: ignore[union-attr]


def test_scale_currency_and_original_text_are_kept():
    amount = parse_amount("Rp1.74T")
    assert (amount.scale, amount.currency, amount.original_text) == ("trillions", "IDR", "Rp1.74T")  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("text", "convention", "expected"),
    [
        ("1.234,5", None, "1234.5"),  # both marks: the last one is the decimal mark
        ("1,234.5", None, "1234.5"),
        ("12,400", None, "12400"),  # a lone comma + 3 digits is grouping by default
        ("1.250", "dot_thousands", "1250"),
        ("1,250", "dot_thousands", "1.250"),  # on a dot-grouped page the comma is decimal
        ("12,5", None, "12.5"),
    ],
)
def test_separator_conventions(text, convention, expected):
    assert parse_amount(text, convention).value == Decimal(expected)  # type: ignore[union-attr]


@pytest.mark.parametrize("text", ["1.250", "12,34,567", "12%", "abc", "1.2.3", "(12", "1e5"])
def test_unreadable_or_ambiguous_numbers_are_rejected(text):
    with pytest.raises(AmountError):
        parse_amount(text)


@pytest.mark.parametrize("text", ["-", "–", "—", "nil"])
def test_nil_is_missing_never_zero(text):
    assert parse_amount(text) is None


# --- Periods -----------------------------------------------------------------------------


def test_headers():
    assert parse_header("31 December 2025").end == date(2025, 12, 31)  # type: ignore[union-attr]
    assert parse_header("December 31, 2025").end == date(2025, 12, 31)  # type: ignore[union-attr]
    assert parse_header("31 Desember 2025").end == date(2025, 12, 31)  # type: ignore[union-attr]
    assert parse_header("2025-12-31").end == date(2025, 12, 31)  # type: ignore[union-attr]
    assert parse_header("Q4 2025").quarter == 4  # type: ignore[union-attr]
    assert parse_header("FY2025").kind == "year"  # type: ignore[union-attr]
    assert parse_header("31 February 2025") is None


def test_header_lines_hold_only_periods():
    assert [h.year for h in header_line("2025      2024") or []] == [2025, 2024]
    assert header_line("Notes   31 Dec 2025   31 Dec 2024") is not None
    assert header_line("The Company was established in 2019") is None


@pytest.mark.parametrize(
    ("header", "kind", "months", "label", "period_type"),
    [
        (Header("year", 2025), "flow", 12, "FY2025", "annual"),
        (Header("year", 2025), "flow", None, "FY2025", "annual"),
        (Header("date", 2025, date(2025, 12, 31)), "flow", 12, "FY2025", "annual"),
        (Header("date", 2025, date(2025, 9, 30)), "flow", 9, "9M ended 2025-09-30", "interim"),
        (Header("quarter", 2025, quarter=4), "flow", 3, "Q4 2025", "quarter"),
        (Header("date", 2025, date(2025, 12, 31)), "stock", None, "2025-12-31", "instant"),
    ],
)
def test_period_resolution(header, kind, months, label, period_type):
    period = resolve_period(header, kind, months, None)
    assert period is not None and (period.label, period.type) == (label, period_type)


@pytest.mark.parametrize(
    ("header", "kind", "months"),
    [
        (Header("date", 2025, date(2025, 12, 31)), "flow", None),  # how long a period?
        (Header("year", 2025), "flow", 9),  # bare year on a nine-month page
        (Header("quarter", 2025, quarter=4), "stock", None),  # which balance-sheet date?
    ],
)
def test_ambiguous_periods_are_not_resolved(header, kind, months):
    assert resolve_period(header, kind, months, None) is None


def test_ambiguous_period_rows_are_rejected_not_stored():
    facts, rejections = run(
        page(
            1,
            ("text", "(in millions of Rupiah)"),
            ("table", "| 31 December 2025 | 31 December 2024\nRevenue | 12,400 | 10,500"),
            heading=INCOME,
        )
    )
    assert facts == []
    assert rejections and all("ambiguous period" in r.reason for r in rejections)


def test_contradictory_duration_wording_rejects_flow_rows():
    facts, _ = run(
        page(
            1,
            ("text", "For the years ended 31 December 2025. Three months ended 31 December 2025."),
            ("text", "(in millions of Rupiah)"),
            ("table", "| 2025 | 2024\nRevenue | 12,400 | 10,500"),
            heading=INCOME,
        )
    )
    assert facts == []


# --- Units & currency --------------------------------------------------------------------


def test_unit_statements():
    u = unit_statement("(expressed in millions of Rupiah, unless otherwise stated)")
    assert (u.scale, u.currency, u.conflicting) == ("millions", "IDR", False)
    assert unit_statement("(Rp billion)").scale == "billions"
    assert unit_statement("dalam jutaan Rupiah").scale == "millions"
    assert unit_statement("an increase in thousands of customers").scale is None
    assert unit_statement("(in millions of Rupiah) ... (in thousands of US Dollars)").conflicting


def test_page_unit_scales_bare_numbers():
    facts, _ = run(
        page(
            1,
            ("text", "For the years ended 31 December 2025 and 2024 (in millions of Rupiah)"),
            ("table", "| 2025 | 2024\nNet income | (1,250) | 980"),
            heading=INCOME,
        )
    )
    assert accepted(facts) == {
        ("net_income", "FY2025"): Decimal("-1250000000"),  # a loss stays negative
        ("net_income", "FY2024"): Decimal("980000000"),
    }


def test_missing_currency_or_scale_is_never_guessed():
    facts, _ = run(
        page(
            1,
            ("text", "For the years ended 31 December 2025 and 2024"),
            ("table", "| 2025 | 2024\nRevenue | 12,400 | 10,500"),
            heading=INCOME,
        )
    )
    assert accepted(facts) == {}
    assert {f.status for f in facts} == {"needs_review"}
    reasons = {r for f in facts for r in f.review_reasons}
    assert {"unit scale not stated", "currency not stated"} <= reasons


def test_impossible_values_need_review():
    facts, _ = run(
        page(
            1,
            ("text", "(in millions of Rupiah)"),
            ("table", "| 31 December 2025\nTotal assets | (45,600)"),
            heading=BALANCE,
        )
    )
    assert [(f.status, f.review_reasons) for f in facts] == [
        ("needs_review", ["negative total assets"])
    ]


# --- Duplicates, conflicts, evidence -------------------------------------------------------

HIGHLIGHTS = ("text", "(in billions of Rupiah)")


def income_page(number: int, revenue: str) -> ParsedPage:
    return page(
        number,
        ("text", "For the years ended 31 December 2025 and 2024"),
        HIGHLIGHTS,
        ("table", f"| 2025 | 2024\nRevenue | {revenue} | 10,500"),
        heading=INCOME,
    )


def test_same_value_on_two_pages_is_one_corroborated_fact():
    facts, _ = run(income_page(1, "12,400"), income_page(2, "12,400"))
    revenue_2025 = [f for f in facts if f.candidate.period.label == "FY2025"]
    assert len(revenue_2025) == 1 and revenue_2025[0].status == "accepted"
    # table row 0.95, year-only header -0.05, corroborated +0.03
    assert revenue_2025[0].confidence == Decimal("0.9300")


def test_conflicting_values_are_never_authoritative():
    facts, _ = run(income_page(1, "12,400"), income_page(2, "12,900"))
    revenue_2025 = [f for f in facts if f.candidate.period.label == "FY2025"]
    assert {f.status for f in revenue_2025} == {"needs_review"}
    assert "different values reported on pages 1, 2" in revenue_2025[0].review_reasons


def test_every_fact_points_at_verbatim_evidence_in_a_chunk():
    pages = [income_page(1, "12,400")]
    facts, _ = run(*pages)
    for f in facts:
        assert f.candidate.source_text in pages[0].text
        assert f.candidate.source_text == "Revenue | 12,400 | 10,500"


def test_evidence_missing_from_the_page_is_rejected():
    from app.extraction import build_facts, extract_candidates

    pages = [income_page(1, "12,400")]
    sections, assignment = detect_sections(pages)
    candidates, _ = extract_candidates(pages, sections, assignment)
    tampered = [
        c.__class__(**{**c.__dict__, "source_text": "Revenue | 99,999"}) for c in candidates
    ]
    facts, rejections = build_facts(tampered, pages, chunk_pages(pages, assignment), assignment)
    assert facts == []
    assert {r.reason for r in rejections} == {"evidence text not on page"}


# --- Labels & text rows --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("label", "metric"),
    [
        ("Revenue", "revenue"),
        ("Net sales", "revenue"),
        ("Pendapatan / Revenue", "revenue"),
        ("Laba tahun berjalan", "net_income"),
        ("Cash and cash equivalents (Note 4)", "cash"),
        ("Total borrowings", "total_debt"),
        ("Jumlah liabilitas", "total_liabilities"),
        ("Total current assets", "current_assets"),
        ("Jumlah liabilitas jangka pendek", "current_liabilities"),
        ("Current assets", None),
        ("Total liabilities and equity", None),
        ("Profit for the year attributable to owners of the parent", None),
        ("Revenue growth", None),
    ],
)
def test_label_matching_is_whole_label(label, metric):
    assert match_metric(label) == metric


def test_text_line_rows_use_the_header_line_above():
    facts, _ = run(
        page(
            1,
            ("text", "For the years ended 31 December 2025 and 2024 (in billions of Rupiah)"),
            ("text", "2025      2024"),
            ("text", "Revenue   12,400   10,500\nRevenue grew 18% compared with 2024."),
            heading=INCOME,
        )
    )
    assert accepted(facts) == {
        ("revenue", "FY2025"): Decimal("12.4") * T,
        ("revenue", "FY2024"): Decimal("10.5") * T,
    }
    assert {f.candidate.source_kind for f in facts} == {"text_line"}


# --- Regressions ---------------------------------------------------------------------------


def test_regression_number_format_is_detected_per_page_not_per_document():
    """Bug: a dot-grouped balance sheet made '12,400' on an English income statement parse
    as 12.4, understating revenue 1000x. Conventions are now detected per page."""
    facts, _ = run(
        income_page(1, "12,400"),
        page(
            2,
            ("text", "As at 31 December 2025 (in millions of Rupiah)"),
            ("table", "| 31 December 2025\nTotal assets | 45.600.000"),
            heading=BALANCE,
        ),
    )
    values = accepted(facts)
    assert values[("revenue", "FY2025")] == Decimal("12.4") * T
    assert values[("total_assets", "2025-12-31")] == Decimal("45.6") * T


def test_regression_unit_word_does_not_turn_grouping_into_a_decimal():
    """Bug: '1,740 bn' parsed as 1.74 billion because a unit suffix forced the lone separator
    to be a decimal mark. A separator followed by exactly three digits is grouping here."""
    assert parse_amount("1,740 bn").value == Decimal("1740") * Decimal(10) ** 9  # type: ignore[union-attr]
    with pytest.raises(AmountError):
        parse_amount("1.740 T")  # dot + three digits with no page convention: ambiguous
