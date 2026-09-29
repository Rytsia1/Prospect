"""Currency semantics (docs/DATA_MODEL.md, "Currency").

Company.reporting_currency is context only; each fact keeps the currency its source states;
Document.document_currency is the primary currency of a document's verified facts. Nothing is
converted: values in different currencies are surfaced for review, never compared.
Extraction tests are pure; API tests run on the in-memory database of tests/test_phase6.py.
"""

import csv
import io
import uuid
from decimal import Decimal

from test_extraction import BALANCE, INCOME, page, run
from test_phase6 import (  # noqa: F401  (pytest fixtures)
    client_a,
    db_engine,
    db_session,
    seed_document,
    user_a,
)

from app.extraction import document_currency
from app.models import Company, Document
from app.processing import ParsedPage
from app.quality import detect_document_anomalies

B = Decimal(10) ** 9
YEARS = ("text", "For the years ended 31 December 2025 and 2024")


def revenue_page(number: int, unit: str, cell: str) -> ParsedPage:
    return page(
        number, YEARS, ("text", unit), ("table", f"| 2025\nRevenue | {cell}"), heading=INCOME
    )


def assets_page(number: int, unit: str, rows: str) -> ParsedPage:
    return page(number, ("text", unit), ("table", f"| 31 December 2025\n{rows}"), heading=BALANCE)


def fy2025(facts):
    return [f for f in facts if f.candidate.period.label == "FY2025"]


# --- Extraction: the fact's currency comes from the document, never from the company ---------


def test_usd_statement_gives_usd_facts_whatever_the_company_reports_in():
    # Test 2. Extraction never sees the company: an IDR company's USD report stays USD.
    facts, _ = run(revenue_page(1, "(in millions of USD)", "14,820"))
    [fact] = fy2025(facts)
    assert (fact.candidate.amount.currency, fact.currency_status, fact.status) == (
        "USD",
        "verified",
        "accepted",
    )
    assert fact.candidate.amount.value == Decimal("14820") * 10**6
    assert document_currency(facts) == "USD"


def test_a_code_printed_on_the_value_beats_the_page_statement():
    # Test 3. A USD document can state one figure in EUR; the value's own code is the evidence.
    # (A bare "EUR 5,000" would still need review for its scale: the page's "millions of USD"
    # does not say whether it applies to the EUR figure.)
    facts, _ = run(revenue_page(1, "(in millions of USD)", "EUR 5.2bn"))
    [fact] = fy2025(facts)
    assert (fact.candidate.amount.currency, fact.currency_status, fact.status) == (
        "EUR",
        "verified",
        "accepted",
    )
    assert fact.review_reasons == [] and fact.candidate.amount.value == Decimal("5.2") * B


def test_unstated_currency_is_missing_never_guessed():
    # Test 4.
    facts, _ = run(revenue_page(1, "(in thousands)", "1,250"))
    [fact] = fy2025(facts)
    assert fact.candidate.amount.value == Decimal("1250000")  # the value is kept
    assert (fact.candidate.amount.currency, fact.currency_status, fact.status) == (
        None,
        "missing",
        "needs_review",
    )
    assert "currency not stated" in fact.review_reasons
    assert document_currency(facts) is None


def test_currency_stated_only_elsewhere_is_inferred_and_needs_review():
    facts, _ = run(
        assets_page(1, "(in millions of USD)", "Total assets | 900"),
        revenue_page(2, "(in millions)", "14,820"),
    )
    [fact] = fy2025(facts)
    assert (fact.candidate.amount.currency, fact.currency_status, fact.status) == (
        "USD",
        "inferred",
        "needs_review",
    )
    assert "currency inferred from other pages; not stated on this page" in fact.review_reasons


def test_same_number_in_two_currencies_is_a_conflict_not_one_value():
    # Test 5. USD 14.82B and EUR 14.82B: equal numbers, different facts. Neither is picked.
    facts, _ = run(
        revenue_page(1, "(in billions of USD)", "14.82"),
        revenue_page(2, "(in billions of EUR)", "14.82"),
    )
    revenue = fy2025(facts)
    assert len(revenue) == 2
    assert {f.status for f in revenue} == {"needs_review"}
    assert {f.currency_status for f in revenue} == {"conflicting"}
    assert {f.candidate.amount.currency for f in revenue} == {"USD", "EUR"}
    assert "different currencies reported on pages 1, 2" in revenue[0].review_reasons


def test_millions_and_billions_are_told_apart():
    # Test 6. The same printed number in millions and in billions is two different amounts...
    facts, _ = run(
        revenue_page(1, "(in millions of USD)", "14,820"),
        revenue_page(2, "(in billions of USD)", "14,820"),
    )
    revenue = fy2025(facts)
    assert {f.candidate.amount.value for f in revenue} == {14820 * 10**6, 14820 * B}
    assert {f.candidate.amount.scale for f in revenue} == {"millions", "billions"}
    assert "different values reported on pages 1, 2" in revenue[0].review_reasons
    # ...while one amount printed at two scales is the same value, corroborated.
    facts, _ = run(
        revenue_page(1, "(in millions of USD)", "14,820"),
        revenue_page(2, "(in billions of USD)", "14.82"),
    )
    [fact] = fy2025(facts)
    assert fact.status == "accepted" and fact.candidate.amount.value == Decimal("14.82") * B


def test_document_currency_is_a_strict_majority_of_verified_facts():
    mixed, _ = run(
        assets_page(1, "(in millions of USD)", "Total assets | 900\nTotal liabilities | 500"),
        revenue_page(2, "(in millions of USD)", "EUR 5.2bn"),
    )
    assert document_currency(mixed) == "USD"  # two USD, one EUR: a legitimate mixed document
    tie, _ = run(
        revenue_page(1, "(in millions of USD)", "14,820"),
        assets_page(2, "(in millions of EUR)", "Total assets | 9"),
    )
    assert document_currency(tie) is None  # no majority: unknown, not guessed


# --- API: companies, quality, diff, watchlist, export ----------------------------------------


def test_indonesian_company_reports_in_idr(client_a):  # noqa: F811
    # Test 1.
    res = client_a.post(
        "/api/v1/companies",
        json={"name": "Bank Nusantara", "country": "ID", "reporting_currency": "IDR"},
    )
    assert res.status_code == 201, res.text
    assert (res.json()["country"], res.json()["reporting_currency"]) == ("ID", "IDR")
    assert "currency" not in res.json()


def test_existing_idr_companies_and_old_clients_keep_working(client_a, db_session, user_a):  # noqa: F811
    # Test 7. A row stored before the rename (the column keeps its value) and a client that
    # still sends the old "currency" field.
    db_session.add(Company(user_id=user_a.id, name="Legacy Tbk", reporting_currency="IDR"))
    db_session.commit()
    listed = {c["name"]: c for c in client_a.get("/api/v1/companies").json()}
    assert listed["Legacy Tbk"]["reporting_currency"] == "IDR"

    res = client_a.post("/api/v1/companies", json={"name": "Old Client Co", "currency": "idr"})
    assert res.status_code == 201 and res.json()["reporting_currency"] == "IDR"
    patched = client_a.patch(f"/api/v1/companies/{res.json()['id']}", json={"currency": "usd"})
    assert patched.status_code == 200 and patched.json()["reporting_currency"] == "USD"


def _to_currency(session, facts, currency, metric_ids=None):
    for f in facts:
        if metric_ids is None or f.metric_id in metric_ids:
            f.currency = currency
    session.commit()


def test_idr_company_keeps_its_usd_facts(client_a, db_session, user_a):  # noqa: F811
    # Test 2, end to end: associating a USD report with an IDR company changes no fact.
    company = client_a.post(
        "/api/v1/companies", json={"name": "Bank Central Asia", "reporting_currency": "IDR"}
    ).json()
    doc, facts = seed_document(db_session, user_a)
    _to_currency(db_session, facts, "USD")
    associated = client_a.post(
        f"/api/v1/companies/{company['id']}/documents", json={"document_id": str(doc.id)}
    )
    assert associated.status_code == 200, associated.text
    detail = client_a.get(f"/api/v1/companies/{company['id']}").json()
    assert detail["reporting_currency"] == "IDR"
    assert {f["currency"] for f in detail["financials"]["facts"]} == {"USD"}


def test_quality_flags_a_currency_conflict_but_not_multi_currency_facts(db_session, user_a):  # noqa: F811
    # Test 5 in the quality system: the same metric and period in IDR and EUR across two
    # reports of one company is a CURRENCY_CONFLICT...
    doc_a, _ = seed_document(db_session, user_a, filename="AR 2024.pdf")
    doc_b, facts_b = seed_document(db_session, user_a, filename="AR 2024 restated.pdf")
    company = Company(user_id=user_a.id, name="Bank Central Asia", reporting_currency="IDR")
    db_session.add(company)
    db_session.flush()
    doc_a.company_id = doc_b.company_id = company.id
    _to_currency(db_session, facts_b, "EUR", {facts_b[0].metric_id})  # revenue only
    issues = detect_document_anomalies(db_session, user_a.id, [doc_a, doc_b])
    conflicts = [i for i in issues if i.rule_type == "CURRENCY_CONFLICT"]
    assert [(i.metric, i.period) for i in conflicts] == [("revenue", "FY2024")]
    assert "EUR, IDR" in conflicts[0].description
    assert not [i for i in issues if i.rule_type == "CONFLICTING_DATA" and i.metric == "revenue"]

    # ...while one report stating revenue in USD and net income in EUR is legitimate: different
    # facts, so no conflict.
    doc_c, facts_c = seed_document(db_session, user_a, filename="Other.pdf", company_name="X")
    _to_currency(db_session, facts_c, "USD")
    _to_currency(db_session, facts_c, "EUR", {facts_c[1].metric_id})  # net income
    issues = detect_document_anomalies(db_session, user_a.id, [doc_c])
    assert not [i for i in issues if i.rule_type in ("CURRENCY_CONFLICT", "CONFLICTING_DATA")]


def test_quality_never_compares_two_companies(db_session, user_a):  # noqa: F811
    doc_a, _ = seed_document(db_session, user_a, company_name="A")
    doc_b, facts_b = seed_document(db_session, user_a, company_name="B")
    for name, doc in (("A", doc_a), ("B", doc_b)):
        company = Company(user_id=user_a.id, name=name)
        db_session.add(company)
        db_session.flush()
        doc.company_id = company.id
    _to_currency(db_session, facts_b, "USD")
    issues = detect_document_anomalies(db_session, user_a.id, [doc_a, doc_b])
    assert not [i for i in issues if i.rule_type in ("CURRENCY_CONFLICT", "CONFLICTING_DATA")]


def test_diff_marks_different_currencies_not_comparable(client_a, db_session, user_a):  # noqa: F811
    doc_a, _ = seed_document(db_session, user_a, filename="AR 2024.pdf")
    doc_b, facts_b = seed_document(db_session, user_a, filename="AR 2024 EUR.pdf")
    _to_currency(db_session, facts_b, "EUR", {facts_b[0].metric_id})
    res = client_a.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc_a.id), "document_b_id": str(doc_b.id)},
    )
    assert res.status_code == 200, res.text
    revenue = next(i for i in res.json()["financial_diff"] if i["metric"] == "revenue")
    assert revenue["status"] == "not_comparable"
    assert (revenue["currency_a"], revenue["currency_b"]) == ("IDR", "EUR")
    originals = {Decimal(revenue["value_a"]), Decimal(revenue["value_b"])}
    assert originals == {Decimal("10800000000000")}  # both kept, nothing converted
    assert revenue["absolute_change"] is None and revenue["percentage_change"] is None


def test_watchlist_labels_each_amount_with_its_own_currency(client_a, db_session, user_a):  # noqa: F811
    company = client_a.post(
        "/api/v1/companies", json={"name": "Bank Central Asia", "reporting_currency": "IDR"}
    ).json()
    doc, facts = seed_document(db_session, user_a)
    stored = db_session.get(Document, doc.id)
    assert stored is not None
    stored.company_id = uuid.UUID(company["id"])
    _to_currency(db_session, facts, "USD")
    _to_currency(db_session, facts, "EUR", {facts[1].metric_id})  # net income
    added = client_a.post("/api/v1/watchlist", json={"company_id": company["id"]})
    assert added.status_code in (200, 201), added.text
    [item] = client_a.get("/api/v1/watchlist").json()
    assert item["reporting_currency"] == "IDR"
    assert (item["currency"], item["net_income_currency"]) == ("USD", "EUR")
    assert item["revenue_formatted"].startswith("USD ")
    assert item["net_income_formatted"].startswith("EUR ")


def test_export_keeps_each_facts_original_currency(client_a, db_session, user_a):  # noqa: F811
    # Test 8. Values, currencies and statuses as stored; nothing converted.
    doc, facts = seed_document(db_session, user_a)
    _to_currency(db_session, facts, "USD", {facts[0].metric_id})  # revenue in USD, rest IDR
    stored = db_session.get(Document, doc.id)
    assert stored is not None
    stored.document_currency = "IDR"
    db_session.commit()
    res = client_a.get(f"/api/v1/documents/{doc.id}/export?format=csv")
    assert res.status_code == 200, res.text
    rows = list(csv.DictReader(io.StringIO(res.content.decode("utf-8-sig"))))
    by_metric = {r["metric"]: r for r in rows}
    revenue = by_metric["revenue"]
    assert (Decimal(revenue["value"]), revenue["currency"]) == (Decimal("10800000000000"), "USD")
    assert by_metric["net_income"]["currency"] == "IDR"
    assert {r["currency_status"] for r in rows} == {"verified"}
    assert {r["document_currency"] for r in rows} == {"IDR"}
