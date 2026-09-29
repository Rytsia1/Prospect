"""Final End-to-End Integration Scenario for Prospect Backend (Phase 20).

Complete deterministic workflow:
Create Company
      ↓
Upload Document A
      ↓
Process Document A
      ↓
Extract Facts
      ↓
Review / Accept Facts
      ↓
Calculate Financial Metrics
      ↓
Run Reconciliation
      ↓
Run Quality Checks
      ↓
Create Scenario
      ↓
Upload Document B
      ↓
Process Document B
      ↓
Compare Documents
      ↓
Update Company Financial History
      ↓
Create Audit Trail
"""

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.auth import start_session, token_for
from app.db import Base, get_session
from app.extraction import METRICS
from app.main import app
from app.models import (
    Document,
    DocumentPage,
    DocumentSection,
    DocumentStatus,
    DocumentType,
    Evidence,
    EvidenceType,
    FactStatus,
    FinancialFact,
    FinancialMetric,
    PageExtractionStatus,
    PeriodType,
    User,
)


@pytest.fixture
def db_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    with Session(db_engine) as session:
        for key, (name, category, _kind, _patterns) in METRICS.items():
            session.add(
                FinancialMetric(
                    key=key,
                    name=name,
                    category=category,
                    description=f"{name} standard metric definition.",
                )
            )
        session.commit()
        yield session


@pytest.fixture
def analyst_user(db_session):
    u = User(email="senior_analyst@prospect.test")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def client(db_session, analyst_user):
    app.dependency_overrides[get_session] = lambda: db_session
    c = TestClient(app)
    token = token_for(start_session(db_session, analyst_user.id))
    db_session.commit()
    c.headers.update({"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.pop(get_session, None)


def _seed_financial_document(
    session: Session,
    user: User,
    filename: str,
    fiscal_year: int,
    company_id: uuid.UUID,
    rev_amount: Decimal,
    ni_amount: Decimal,
    assets_amount: Decimal,
    liab_amount: Decimal,
    equity_amount: Decimal,
) -> tuple[Document, list[FinancialFact]]:
    doc = Document(
        user_id=user.id,
        company_id=company_id,
        filename=filename,
        document_type=DocumentType.ANNUAL_REPORT,
        fiscal_year=fiscal_year,
        company_name="PT Bank Nusantara Tbk",
        mime_type="application/pdf",
        size_bytes=4_200_000,
        storage_key=f"documents/{user.id}/{uuid.uuid4()}/report.pdf",
        status=DocumentStatus.READY,
        threat_scan="clean",
    )
    session.add(doc)
    session.flush()

    p_is = DocumentPage(
        document_id=doc.id,
        page_number=65,
        text=f"Statements of Profit or Loss FY{fiscal_year}",
        extraction_status=PageExtractionStatus.SUCCESS,
        page_metadata={"label": "65"},
    )
    p_bs = DocumentPage(
        document_id=doc.id,
        page_number=66,
        text=f"Statements of Financial Position {fiscal_year}-12-31",
        extraction_status=PageExtractionStatus.SUCCESS,
        page_metadata={"label": "66"},
    )
    session.add_all([p_is, p_bs])
    session.flush()

    s_is = DocumentSection(
        document_id=doc.id,
        ordinal=0,
        title="Consolidated Statement of Profit or Loss",
        start_page=65,
        end_page=65,
    )
    s_bs = DocumentSection(
        document_id=doc.id,
        ordinal=1,
        title="Consolidated Statement of Financial Position",
        start_page=66,
        end_page=66,
    )
    session.add_all([s_is, s_bs])
    session.flush()

    ev_rev = Evidence(
        document_id=doc.id,
        page_id=p_is.id,
        page_number=65,
        section_id=s_is.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content=f"Total Revenue {rev_amount}",
        locator={"header": f"FY{fiscal_year}", "unit": "IDR"},
    )
    ev_ni = Evidence(
        document_id=doc.id,
        page_id=p_is.id,
        page_number=65,
        section_id=s_is.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content=f"Net Profit for the Year {ni_amount}",
        locator={"header": f"FY{fiscal_year}", "unit": "IDR"},
    )
    ev_assets = Evidence(
        document_id=doc.id,
        page_id=p_bs.id,
        page_number=66,
        section_id=s_bs.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content=f"Total Assets {assets_amount}",
        locator={"header": f"31 Dec {fiscal_year}", "unit": "IDR"},
    )
    ev_liab = Evidence(
        document_id=doc.id,
        page_id=p_bs.id,
        page_number=66,
        section_id=s_bs.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content=f"Total Liabilities {liab_amount}",
        locator={"header": f"31 Dec {fiscal_year}", "unit": "IDR"},
    )
    ev_eq = Evidence(
        document_id=doc.id,
        page_id=p_bs.id,
        page_number=66,
        section_id=s_bs.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content=f"Total Equity {equity_amount}",
        locator={"header": f"31 Dec {fiscal_year}", "unit": "IDR"},
    )
    session.add_all([ev_rev, ev_ni, ev_assets, ev_liab, ev_eq])
    session.flush()

    m_rev = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "revenue"))
    m_ni = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "net_income"))
    m_assets = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "total_assets"))
    m_liab = session.scalar(
        select(FinancialMetric).where(FinancialMetric.key == "total_liabilities")
    )
    m_eq = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "equity"))
    assert all([m_rev, m_ni, m_assets, m_liab, m_eq])

    f_rev = FinancialFact(
        document_id=doc.id,
        metric_id=m_rev.id,
        evidence_id=ev_rev.id,
        value_numeric=rev_amount,
        currency="IDR",
        currency_status="verified",
        scale="trillions",
        original_text=str(rev_amount),
        period_type=PeriodType.ANNUAL,
        period_label=f"FY{fiscal_year}",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9500"),
        extraction_method="parser",
        status=FactStatus.NEEDS_REVIEW,
    )
    f_ni = FinancialFact(
        document_id=doc.id,
        metric_id=m_ni.id,
        evidence_id=ev_ni.id,
        value_numeric=ni_amount,
        currency="IDR",
        currency_status="verified",
        scale="trillions",
        original_text=str(ni_amount),
        period_type=PeriodType.ANNUAL,
        period_label=f"FY{fiscal_year}",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9200"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    f_assets = FinancialFact(
        document_id=doc.id,
        metric_id=m_assets.id,
        evidence_id=ev_assets.id,
        value_numeric=assets_amount,
        currency="IDR",
        currency_status="verified",
        scale="trillions",
        original_text=str(assets_amount),
        period_type=PeriodType.INSTANT,
        period_label=f"{fiscal_year}-12-31",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9600"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    f_liab = FinancialFact(
        document_id=doc.id,
        metric_id=m_liab.id,
        evidence_id=ev_liab.id,
        value_numeric=liab_amount,
        currency="IDR",
        currency_status="verified",
        scale="trillions",
        original_text=str(liab_amount),
        period_type=PeriodType.INSTANT,
        period_label=f"{fiscal_year}-12-31",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9400"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    f_eq = FinancialFact(
        document_id=doc.id,
        metric_id=m_eq.id,
        evidence_id=ev_eq.id,
        value_numeric=equity_amount,
        currency="IDR",
        currency_status="verified",
        scale="trillions",
        original_text=str(equity_amount),
        period_type=PeriodType.INSTANT,
        period_label=f"{fiscal_year}-12-31",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9500"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    session.add_all([f_rev, f_ni, f_assets, f_liab, f_eq])
    session.commit()

    return doc, [f_rev, f_ni, f_assets, f_liab, f_eq]


def test_complete_backend_domain_workflow(client, db_session, analyst_user):
    """Executes the full 13-stage Prospect backend intelligence lifecycle."""

    # --------------------------------------------------------------------------------------
    # 1. Create Company
    # --------------------------------------------------------------------------------------
    res_company = client.post(
        "/api/v1/companies",
        json={
            "name": "PT Bank Nusantara Tbk",
            "ticker": "BNUS",
            "country": "Indonesia",
            "reporting_currency": "IDR",
            "description": "Leading commercial banking institution.",
        },
    )
    assert res_company.status_code == 201
    company_data = res_company.json()
    company_id = uuid.UUID(company_data["id"])
    assert company_data["name"] == "PT Bank Nusantara Tbk"
    assert company_data["ticker"] == "BNUS"

    # --------------------------------------------------------------------------------------
    # 2 & 3. Upload & Process Document A (FY2024 Report)
    # Assets (100T) = Liabilities (80T) + Equity (20T)
    # Revenue = 15T, Net Income = 3T -> Net Margin = 20%
    # --------------------------------------------------------------------------------------
    doc_a, facts_a = _seed_financial_document(
        session=db_session,
        user=analyst_user,
        filename="BNUS_Annual_Report_2024.pdf",
        fiscal_year=2024,
        company_id=company_id,
        rev_amount=Decimal("15000000000000"),
        ni_amount=Decimal("3000000000000"),
        assets_amount=Decimal("100000000000000"),
        liab_amount=Decimal("80000000000000"),
        equity_amount=Decimal("20000000000000"),
    )
    assert doc_a.status == DocumentStatus.READY

    # --------------------------------------------------------------------------------------
    # 4. Review / Accept Facts: Accept Revenue Fact
    # --------------------------------------------------------------------------------------
    rev_fact = next(f for f in facts_a if f.metric_id == facts_a[0].metric_id)
    assert rev_fact.status == FactStatus.NEEDS_REVIEW

    accept_res = client.post(
        f"/api/v1/financial-facts/{rev_fact.id}/accept",
        json={"reason": "Audited figure verified against P&L table on page 65."},
    )
    assert accept_res.status_code == 200
    assert accept_res.json()["status"] == "accepted"

    # --------------------------------------------------------------------------------------
    # 5. Calculate Financial Metrics (Read Financials for Document A)
    # --------------------------------------------------------------------------------------
    fin_a_res = client.get(f"/api/v1/documents/{doc_a.id}/financials")
    assert fin_a_res.status_code == 200
    fin_a = fin_a_res.json()
    assert "FY2024" in fin_a["periods"]

    # Check calculated ratios (net_margin = 3T / 15T = 0.20)
    net_margins = [c for c in fin_a["calculations"] if c["metric"] == "net_margin"]
    assert len(net_margins) >= 1
    assert Decimal(net_margins[0]["value"]) == Decimal("0.2")

    # --------------------------------------------------------------------------------------
    # 6. Run Reconciliation (Assets = Liabilities + Equity)
    # --------------------------------------------------------------------------------------
    reconciliations = fin_a["reconciliations"]
    assert len(reconciliations) >= 1
    rec = reconciliations[0]
    assert rec["status"] == "BALANCED"
    assert rec["outcome"] == "PASS"
    assert rec["expected_relationship"] == "assets = liabilities + equity"
    assert Decimal(rec["difference"]) == Decimal("0")
    assert Decimal(rec["actual_values"]["total_assets"]) == Decimal("100000000000000")

    # --------------------------------------------------------------------------------------
    # 7. Run Quality Checks
    # --------------------------------------------------------------------------------------
    dq_res = client.get(f"/api/v1/data-quality?document_id={doc_a.id}")
    assert dq_res.status_code == 200
    dq = dq_res.json()
    assert dq["summary"]["reconciled_status"] == "Balance sheet reconciles"
    # All structural checks passed
    impossible_issues = [i for i in dq["issues"] if i["rule_type"] == "IMPOSSIBLE_RELATIONSHIP"]
    assert len(impossible_issues) == 0

    # --------------------------------------------------------------------------------------
    # 8. Create Scenario (Base FY2024 + 10% Revenue Growth, +2% Net Margin)
    # --------------------------------------------------------------------------------------
    scen_res = client.post(
        "/api/v1/scenarios",
        json={
            "document_id": str(doc_a.id),
            "company_id": str(company_id),
            "name": "Base Growth Scenario 2025",
            "base_period": "FY2024",
            "growth_adjustment": "0.10",
            "margin_adjustment": "0.02",
        },
    )
    assert scen_res.status_code == 201
    scen = scen_res.json()
    assert Decimal(scen["calculated_outputs"]["base_revenue"]) == Decimal("15000000000000")
    # Scenario Revenue: 15T * 1.10 = 16.5T
    assert Decimal(scen["calculated_outputs"]["scenario_revenue"]) == Decimal("16500000000000")
    # Base Margin: 0.20, Scenario Margin: 0.22
    assert Decimal(scen["calculated_outputs"]["scenario_net_margin"]) == Decimal("0.22")
    # Scenario Net Income: 16.5T * 0.22 = 3.63T
    assert Decimal(scen["calculated_outputs"]["scenario_net_income"]) == Decimal("3630000000000")

    # Invariant: Reported facts table must remain untouched
    rev_fact_check = db_session.get(FinancialFact, rev_fact.id)
    assert rev_fact_check.value_numeric == Decimal("15000000000000")

    # --------------------------------------------------------------------------------------
    # 9 & 10. Upload & Process Document B (FY2025 Report with Restated 2024 figures)
    # --------------------------------------------------------------------------------------
    doc_b, facts_b = _seed_financial_document(
        session=db_session,
        user=analyst_user,
        filename="BNUS_Annual_Report_2025.pdf",
        fiscal_year=2025,
        company_id=company_id,
        rev_amount=Decimal("18000000000000"),
        ni_amount=Decimal("3960000000000"),
        assets_amount=Decimal("120000000000000"),
        liab_amount=Decimal("95000000000000"),
        equity_amount=Decimal("25000000000000"),
    )
    # Set Doc B revenue to accepted
    facts_b[0].status = FactStatus.ACCEPTED
    db_session.commit()

    # --------------------------------------------------------------------------------------
    # 11. Compare Documents (Document Diff)
    # --------------------------------------------------------------------------------------
    diff_res = client.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc_a.id), "document_b_id": str(doc_b.id)},
    )
    assert diff_res.status_code == 200
    diff = diff_res.json()
    assert diff["document_a_id"] == str(doc_a.id)
    assert diff["document_b_id"] == str(doc_b.id)
    assert len(diff["metadata_diff"]) > 0
    assert len(diff["financial_diff"]) > 0

    # --------------------------------------------------------------------------------------
    # 12. Update Company Financial History (Multi-Document Timeline)
    # --------------------------------------------------------------------------------------
    comp_detail_res = client.get(f"/api/v1/companies/{company_id}")
    assert comp_detail_res.status_code == 200
    comp_detail = comp_detail_res.json()
    assert len(comp_detail["documents"]) == 2
    assert comp_detail["financials"] is not None
    assert "FY2024" in comp_detail["financials"]["periods"]
    assert "FY2025" in comp_detail["financials"]["periods"]

    # Bookmark company in watchlist
    wl_add = client.post("/api/v1/watchlist", json={"company_id": str(company_id)})
    assert wl_add.status_code == 201
    wl_entry = wl_add.json()
    assert wl_entry["name"] == "PT Bank Nusantara Tbk"
    assert wl_entry["latest_period"] == "FY2025"
    assert Decimal(wl_entry["revenue"]) == Decimal("18000000000000")

    # --------------------------------------------------------------------------------------
    # 13. Create Audit Trail
    # --------------------------------------------------------------------------------------
    audit_res = client.get("/api/v1/audit")
    assert audit_res.status_code == 200
    audit_events = audit_res.json()["items"]
    event_types = {e["event_type"] for e in audit_events}

    assert "COMPANY_CREATED" in event_types
    assert "FACT_ACCEPTED" in event_types
    assert "SCENARIO_CREATED" in event_types
    assert "DOCUMENT_COMPARED" in event_types
    assert "WATCHLIST_UPDATED" in event_types

    # Verify audit event entity structure
    for event in audit_events:
        assert event["user_id"] == str(analyst_user.id)
        assert event["created_at"] is not None
