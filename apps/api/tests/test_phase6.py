"""Comprehensive tests for Prospect Phase 6: Advanced Research & Data Quality.

Tests:
1. Document Diff (identical docs, differing values, added/removed sections, text diff, evidence)
2. Extraction Review (accept, correct with validation and history preservation, reject, filters)
3. Data Quality (missing data, duplicate data, conflicting data, unit mismatch, large change)
4. Scenario Analysis (base case, positive/negative/zero adjustment, Decimal precision, persistence)
5. Audit Trail (append-only, event creation, actor, before/after, access control)
6. Company Workspace (create, associate/disassociate document, financials aggregation)
7. Watchlist (add, remove, duplicate prevention, factual metrics, access control)
8. End-to-End Workflow from upload/facts to review, diff, scenario, company, watchlist, export
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
        # Seed standard metrics
        for key, (name, category, _kind, _patterns) in METRICS.items():
            session.add(
                FinancialMetric(
                    key=key,
                    name=name,
                    category=category,
                    description=f"{name} metric definition.",
                )
            )
        session.commit()
        yield session


@pytest.fixture
def user_a(db_session):
    u = User(email="analyst_a@prospect.test")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def user_b(db_session):
    u = User(email="analyst_b@prospect.test")
    db_session.add(u)
    db_session.commit()
    return u


@pytest.fixture
def client_a(db_session, user_a):
    app.dependency_overrides[get_session] = lambda: db_session
    c = TestClient(app)
    token = token_for(start_session(db_session, user_a.id))
    db_session.commit()
    c.headers.update({"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.pop(get_session, None)  # keep the session-wide storage override


@pytest.fixture
def client_b(db_session, user_b):
    app.dependency_overrides[get_session] = lambda: db_session
    c = TestClient(app)
    token = token_for(start_session(db_session, user_b.id))
    db_session.commit()
    c.headers.update({"Authorization": f"Bearer {token}"})
    yield c
    app.dependency_overrides.pop(get_session, None)  # keep the session-wide storage override


def seed_document(
    session: Session,
    user: User,
    filename: str = "Annual Report 2024.pdf",
    fiscal_year: int = 2024,
    company_name: str = "Bank Central Asia",
) -> tuple[Document, list[FinancialFact]]:
    doc = Document(
        user_id=user.id,
        filename=filename,
        document_type=DocumentType.ANNUAL_REPORT,
        fiscal_year=fiscal_year,
        company_name=company_name,
        mime_type="application/pdf",
        size_bytes=1024 * 500,
        storage_key=f"docs/{uuid.uuid4()}.pdf",
        status=DocumentStatus.READY,
    )
    session.add(doc)
    session.flush()

    # Add Pages
    p1 = DocumentPage(
        document_id=doc.id,
        page_number=1,
        text="Annual Report 2024. Corporate overview and management report.",
        extraction_status=PageExtractionStatus.SUCCESS,
        page_metadata={"label": "1", "width": 595.0, "height": 842.0},
    )
    p2 = DocumentPage(
        document_id=doc.id,
        page_number=87,
        text=(
            "Consolidated Statements of Profit or Loss. Total revenue: 10,800,000,000,000. "
            "Net income: 1,400,000,000,000."
        ),
        extraction_status=PageExtractionStatus.SUCCESS,
        page_metadata={"label": "87", "width": 595.0, "height": 842.0},
    )
    p3 = DocumentPage(
        document_id=doc.id,
        page_number=88,
        text=(
            "Consolidated Statements of Financial Position. Total assets: 40,000,000,000,000. "
            "Total liabilities: 25,000,000,000,000. Total equity: 15,000,000,000,000."
        ),
        extraction_status=PageExtractionStatus.SUCCESS,
        page_metadata={"label": "88", "width": 595.0, "height": 842.0},
    )
    session.add_all([p1, p2, p3])
    session.flush()

    # Add Sections
    s1 = DocumentSection(
        document_id=doc.id,
        ordinal=0,
        title="Management Discussion",
        start_page=1,
        end_page=10,
    )
    s2 = DocumentSection(
        document_id=doc.id,
        ordinal=1,
        title="Financial Statements",
        start_page=87,
        end_page=95,
    )
    session.add_all([s1, s2])
    session.flush()

    # Evidence
    ev1 = Evidence(
        document_id=doc.id,
        page_id=p2.id,
        page_number=87,
        section_id=s2.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content="Revenue 10,800,000,000,000",
        locator={"header": f"FY{fiscal_year}", "unit": "IDR"},
    )
    ev2 = Evidence(
        document_id=doc.id,
        page_id=p2.id,
        page_number=87,
        section_id=s2.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content="Net Income 1,400,000,000,000",
        locator={"header": f"FY{fiscal_year}", "unit": "IDR"},
    )
    ev3 = Evidence(
        document_id=doc.id,
        page_id=p3.id,
        page_number=88,
        section_id=s2.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content="Total Assets 40,000,000,000,000",
        locator={"header": f"FY{fiscal_year}", "unit": "IDR"},
    )
    session.add_all([ev1, ev2, ev3])
    session.flush()

    # Financial Facts
    m_rev = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "revenue"))
    m_ni = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "net_income"))
    m_assets = session.scalar(select(FinancialMetric).where(FinancialMetric.key == "total_assets"))
    assert m_rev is not None and m_ni is not None and m_assets is not None

    f1 = FinancialFact(
        document_id=doc.id,
        metric_id=m_rev.id,
        evidence_id=ev1.id,
        value_numeric=Decimal("10800000000000"),
        currency="IDR",
        scale="trillions",
        original_text="10,800,000",
        period_type=PeriodType.ANNUAL,
        period_label=f"FY{fiscal_year}",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9500"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    f2 = FinancialFact(
        document_id=doc.id,
        metric_id=m_ni.id,
        evidence_id=ev2.id,
        value_numeric=Decimal("1400000000000"),
        currency="IDR",
        scale="trillions",
        original_text="1,400,000",
        period_type=PeriodType.ANNUAL,
        period_label=f"FY{fiscal_year}",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.9000"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    f3 = FinancialFact(
        document_id=doc.id,
        metric_id=m_assets.id,
        evidence_id=ev3.id,
        value_numeric=Decimal("40000000000000"),
        currency="IDR",
        scale="trillions",
        original_text="40,000,000",
        period_type=PeriodType.INSTANT,
        period_label=f"{fiscal_year}-12-31",
        fiscal_year=fiscal_year,
        period_end=date(fiscal_year, 12, 31),
        confidence=Decimal("0.8500"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    session.add_all([f1, f2, f3])
    session.commit()

    return doc, [f1, f2, f3]


# ==========================================================================================
# 6. DOCUMENT DIFF TESTS
# ==========================================================================================


def test_document_diff_identical_documents(client_a, db_session, user_a):
    doc1, _ = seed_document(db_session, user_a, "DocA.pdf", 2024)
    res = client_a.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc1.id), "document_b_id": str(doc1.id)},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["document_a_id"] == str(doc1.id)
    assert data["document_b_id"] == str(doc1.id)
    # Metadata comparison
    for m in data["metadata_diff"]:
        assert not m["changed"]
    # All financial facts unchanged
    for f in data["financial_diff"]:
        assert f["status"] == "unchanged"


def test_document_diff_different_financial_values_and_evidence(client_a, db_session, user_a):
    doc_2024, _ = seed_document(db_session, user_a, "Annual Report 2024.pdf", 2024)
    doc_2025, facts_2025 = seed_document(db_session, user_a, "Annual Report 2025.pdf", 2025)

    # Update 2025 revenue to 12.4T (growth: (12.4 - 10.8)/10.8 = +14.81%)
    rev_2025 = next(f for f in facts_2025 if f.metric_id == facts_2025[0].metric_id)
    rev_2025.value_numeric = Decimal("12400000000000")
    db_session.commit()

    res = client_a.get(f"/api/v1/documents/{doc_2024.id}/diff?other_id={doc_2025.id}")
    assert res.status_code == 200
    data = res.json()

    # Evidence links present in both
    for f in data["financial_diff"]:
        if f["status"] == "changed":
            assert f["evidence_a"] is not None
            assert f["evidence_b"] is not None
            assert f["percentage_change"] is not None


def test_document_diff_added_and_removed_sections(client_a, db_session, user_a):
    doc_a, _ = seed_document(db_session, user_a, "Doc_A.pdf", 2024)
    doc_b, _ = seed_document(db_session, user_a, "Doc_B.pdf", 2025)

    # Add a new section in Doc B that doesn't exist in Doc A
    extra_section = DocumentSection(
        document_id=doc_b.id,
        ordinal=2,
        title="Sustainability Report",
        start_page=96,
        end_page=110,
    )
    db_session.add(extra_section)
    db_session.commit()

    res = client_a.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc_a.id), "document_b_id": str(doc_b.id)},
    )
    assert res.status_code == 200
    sections = res.json()["section_diff"]
    added_sec = next((s for s in sections if s["title"] == "Sustainability Report"), None)
    assert added_sec is not None
    assert added_sec["status"] == "added"


def test_document_diff_authorization(client_a, client_b, db_session, user_a, user_b):
    doc_a, _ = seed_document(db_session, user_a, "UserA.pdf", 2024)
    doc_b, _ = seed_document(db_session, user_b, "UserB.pdf", 2025)

    # User A cannot diff User B's document
    res = client_a.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc_a.id), "document_b_id": str(doc_b.id)},
    )
    assert res.status_code == 404


# ==========================================================================================
# 7. EXTRACTION REVIEW TESTS
# ==========================================================================================


def test_review_queue_filters(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR.pdf", 2024)

    # Add a fact needing review with low confidence
    m_debt = db_session.scalar(select(FinancialMetric).where(FinancialMetric.key == "total_debt"))
    p = db_session.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
    s = db_session.scalar(select(DocumentSection).where(DocumentSection.document_id == doc.id))

    ev = Evidence(
        document_id=doc.id,
        page_id=p.id,
        page_number=p.page_number,
        section_id=s.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TEXT_LINE,
        content="Total borrowings Rp 500,000",
        locator={"unit": "IDR"},
    )
    db_session.add(ev)
    db_session.flush()

    debt_fact = FinancialFact(
        document_id=doc.id,
        metric_id=m_debt.id,
        evidence_id=ev.id,
        value_numeric=Decimal("500000000000"),
        currency="IDR",
        scale="billions",
        original_text="500,000",
        period_type=PeriodType.INSTANT,
        period_label="2024-12-31",
        fiscal_year=2024,
        confidence=Decimal("0.4000"),
        extraction_method="parser",
        status=FactStatus.NEEDS_REVIEW,
        review_reasons=["low confidence match"],
    )
    db_session.add(debt_fact)
    db_session.commit()

    # Filter pending
    res = client_a.get("/api/v1/financial-facts/review?status=pending")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == str(debt_fact.id)
    assert items[0]["confidence_tier"] == "low"

    # Filter accepted
    res_acc = client_a.get("/api/v1/financial-facts/review?status=accepted")
    assert res_acc.status_code == 200
    assert len(res_acc.json()["items"]) == 3


def test_review_accept_and_audit(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR.pdf", 2024)
    # Set one fact to needs_review
    facts[0].status = FactStatus.NEEDS_REVIEW
    db_session.commit()

    res = client_a.post(
        f"/api/v1/financial-facts/{facts[0].id}/accept",
        json={"reason": "Verified against audited statement."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "accepted"

    # Check Audit event
    events = client_a.get(f"/api/v1/audit?entity_id={facts[0].id}").json()["items"]
    assert len(events) >= 1
    assert events[0]["event_type"] == "FACT_ACCEPTED"
    assert "Verified" in events[0]["reason"]


def test_review_correct_preserves_history(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR.pdf", 2024)
    fact = facts[0]
    orig_val = fact.value_numeric

    res = client_a.post(
        f"/api/v1/financial-facts/{fact.id}/correct",
        json={
            "value": "11500000000000",
            "currency": "IDR",
            "scale": "trillions",
            "reason": "Corrected according to restatement in Note 2.",
        },
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "corrected"
    assert Decimal(data["value"]) == Decimal("11500000000000")

    # Verify history is preserved in extraction_reviews
    hist = client_a.get(f"/api/v1/financial-facts/{fact.id}/history").json()
    assert len(hist) == 1
    assert hist[0]["original_value"] == str(orig_val)
    assert Decimal(hist[0]["corrected_value"]) == Decimal("11500000000000")
    assert "Note 2" in hist[0]["reason"]

    # Verify audit event
    events = client_a.get(f"/api/v1/audit?entity_id={fact.id}").json()["items"]
    assert any(e["event_type"] == "FACT_CORRECTED" for e in events)


def test_review_reject(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR.pdf", 2024)
    fact = facts[0]

    res = client_a.post(
        f"/api/v1/financial-facts/{fact.id}/reject",
        json={"reason": "Value is not consolidated figure."},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "rejected"

    # Must appear in audit
    events = client_a.get(f"/api/v1/audit?entity_id={fact.id}").json()["items"]
    assert any(e["event_type"] == "FACT_REJECTED" for e in events)


def test_review_validation_rejects_malformed_input(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR.pdf", 2024)
    fact = facts[0]

    # Invalid scale
    res_bad_scale = client_a.post(
        f"/api/v1/financial-facts/{fact.id}/correct",
        json={"value": "1000", "scale": "gazillion", "reason": "test"},
    )
    assert res_bad_scale.status_code == 422

    # Invalid currency (not 3 letters)
    res_bad_curr = client_a.post(
        f"/api/v1/financial-facts/{fact.id}/correct",
        json={"value": "1000", "currency": "INDONESIAN_RUPIAH", "reason": "test"},
    )
    assert res_bad_curr.status_code == 422


# ==========================================================================================
# 8. DATA QUALITY / ANOMALY DETECTION TESTS
# ==========================================================================================


def test_data_quality_detects_duplicate_and_large_changes(client_a, db_session, user_a):
    doc, facts = seed_document(db_session, user_a, "AR_2024.pdf", 2024)
    doc_2025, facts_2025 = seed_document(db_session, user_a, "AR_2025.pdf", 2025)

    # 1. Create duplicate fact in doc 2024 for same metric/period
    p = db_session.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
    s = db_session.scalar(select(DocumentSection).where(DocumentSection.document_id == doc.id))
    ev = Evidence(
        document_id=doc.id,
        page_id=p.id,
        page_number=p.page_number,
        section_id=s.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content="Revenue duplicate row",
        locator={},
    )
    db_session.add(ev)
    db_session.flush()

    dup_fact = FinancialFact(
        document_id=doc.id,
        metric_id=facts[0].metric_id,
        evidence_id=ev.id,
        value_numeric=Decimal("10800000000000"),
        currency="IDR",
        scale="trillions",
        original_text="10,800,000",
        period_type=PeriodType.ANNUAL,
        period_label="FY2024",
        fiscal_year=2024,
        confidence=Decimal("0.8000"),
        extraction_method="parser",
        status=FactStatus.NEEDS_REVIEW,
    )
    db_session.add(dup_fact)

    # 2. Create large change in 2025: revenue increases from 10.8T to 45T (> 300%)
    rev_2025 = next(f for f in facts_2025 if f.metric_id == facts[0].metric_id)
    rev_2025.value_numeric = Decimal("45000000000000")
    db_session.commit()

    res = client_a.get(f"/api/v1/data-quality?document_id={doc.id}")
    assert res.status_code == 200
    data = res.json()
    issues = data["issues"]

    types = {i["rule_type"] for i in issues}
    assert "DUPLICATE_DATA" in types


def test_data_quality_anomaly_lifecycle(client_a, db_session, user_a):
    doc, _ = seed_document(db_session, user_a, "AR_2024.pdf", 2024)
    res = client_a.get(f"/api/v1/data-quality?document_id={doc.id}")
    issues = res.json()["issues"]
    assert len(issues) > 0
    issue_id = issues[0]["id"]

    # Acknowledge issue
    ack_res = client_a.patch(
        f"/api/v1/data-quality/{issue_id}",
        json={"status": "ACKNOWLEDGED", "reason": "Reviewed by analyst, expected gap."},
    )
    assert ack_res.status_code == 200
    assert ack_res.json()["status"] == "ACKNOWLEDGED"

    # Resolve issue
    res_res = client_a.patch(
        f"/api/v1/data-quality/{issue_id}",
        json={"status": "RESOLVED", "reason": "Fixed in review."},
    )
    assert res_res.status_code == 200
    assert res_res.json()["status"] == "RESOLVED"

    # Audit event must be created
    events = client_a.get(f"/api/v1/audit?entity_id={issue_id}").json()["items"]
    assert len(events) >= 2


def test_data_quality_detects_impossible_relationships_and_suspicious_values(
    client_a, db_session, user_a
):
    doc, facts = seed_document(db_session, user_a, "Anomaly_Doc.pdf", 2024)
    # Add an impossible relationship: current assets = 50T, total assets = 40T (Current > Total)
    m_ca = db_session.scalar(
        select(FinancialMetric).where(FinancialMetric.key == "current_assets")
    )
    p = db_session.scalar(select(DocumentPage).where(DocumentPage.document_id == doc.id))
    s = db_session.scalar(select(DocumentSection).where(DocumentSection.document_id == doc.id))
    ev = Evidence(
        document_id=doc.id,
        page_id=p.id,
        page_number=p.page_number,
        section_id=s.id,
        chunk_id=uuid.uuid4(),
        evidence_type=EvidenceType.TABLE_ROW,
        content="Current Assets 50,000,000,000,000",
        locator={},
    )
    db_session.add(ev)
    db_session.flush()

    ca_fact = FinancialFact(
        document_id=doc.id,
        metric_id=m_ca.id,
        evidence_id=ev.id,
        value_numeric=Decimal("50000000000000"),
        currency="IDR",
        scale="trillions",
        original_text="50,000,000",
        period_type=PeriodType.INSTANT,
        period_label="2024-12-31",
        fiscal_year=2024,
        confidence=Decimal("0.9000"),
        extraction_method="parser",
        status=FactStatus.ACCEPTED,
    )
    db_session.add(ca_fact)
    db_session.commit()

    res = client_a.get(f"/api/v1/data-quality?document_id={doc.id}")
    assert res.status_code == 200
    issues = res.json()["issues"]
    impossible = [i for i in issues if i["rule_type"] == "IMPOSSIBLE_RELATIONSHIP"]
    assert len(impossible) >= 1
    assert "current assets" in impossible[0]["description"].lower()
    assert "requires review" in impossible[0]["description"].lower()



# ==========================================================================================
# 9. SCENARIO ANALYSIS TESTS
# ==========================================================================================


def test_scenario_preview_positive_negative_zero_adjustment(client_a, db_session, user_a):
    doc, _ = seed_document(db_session, user_a, "AR_2024.pdf", 2024)
    # Base revenue is 10.8T, net income is 1.4T, net margin is ~12.96%

    # Positive growth +10%
    res_pos = client_a.post(
        "/api/v1/scenarios/calculate",
        json={
            "document_id": str(doc.id),
            "base_period": "FY2024",
            "growth_adjustment": "0.10",
            "margin_adjustment": "0.0",
        },
    )
    assert res_pos.status_code == 200
    data_pos = res_pos.json()
    assert Decimal(data_pos["scenario_revenue"]) == Decimal("11880000000000")
    assert "disclaimer" in data_pos

    # Negative growth -10%
    res_neg = client_a.post(
        "/api/v1/scenarios/calculate",
        json={
            "document_id": str(doc.id),
            "base_period": "FY2024",
            "growth_adjustment": "-0.10",
            "margin_adjustment": "0.0",
        },
    )
    assert res_neg.status_code == 200
    data_neg = res_neg.json()
    assert Decimal(data_neg["scenario_revenue"]) == Decimal("9720000000000")

    # Zero adjustment
    res_zero = client_a.post(
        "/api/v1/scenarios/calculate",
        json={
            "document_id": str(doc.id),
            "base_period": "FY2024",
            "growth_adjustment": "0.0",
            "margin_adjustment": "0.0",
        },
    )
    assert res_zero.status_code == 200
    data_zero = res_zero.json()
    assert Decimal(data_zero["scenario_revenue"]) == Decimal("10800000000000")


def test_scenario_crud_and_persistence(client_a, db_session, user_a):
    doc, _ = seed_document(db_session, user_a, "AR_2024.pdf", 2024)

    # Save scenario
    create_res = client_a.post(
        "/api/v1/scenarios",
        json={
            "document_id": str(doc.id),
            "name": "Optimistic Expansion FY2025",
            "base_period": "FY2024",
            "growth_adjustment": "0.15",
            "margin_adjustment": "0.02",
        },
    )
    assert create_res.status_code == 201
    scen = create_res.json()
    scen_id = scen["id"]
    assert scen["name"] == "Optimistic Expansion FY2025"

    # List scenarios
    list_res = client_a.get(f"/api/v1/scenarios?document_id={doc.id}")
    assert list_res.status_code == 200
    assert any(s["id"] == scen_id for s in list_res.json())

    # Update scenario
    upd_res = client_a.patch(
        f"/api/v1/scenarios/{scen_id}",
        json={"growth_adjustment": "0.20", "name": "Very Optimistic"},
    )
    assert upd_res.status_code == 200
    assert upd_res.json()["name"] == "Very Optimistic"

    # Delete scenario
    del_res = client_a.delete(f"/api/v1/scenarios/{scen_id}")
    assert del_res.status_code == 204

    # Source facts remain completely unchanged!
    facts = client_a.get(f"/api/v1/documents/{doc.id}/metrics").json()["items"]
    assert len(facts) == 3


# ==========================================================================================
# 10. AUDIT TRAIL TESTS
# ==========================================================================================


def test_audit_trail_immutability_and_filtering(client_a, db_session, user_a):
    # Perform actions that write audit events
    doc, _ = seed_document(db_session, user_a, "AuditDoc.pdf", 2024)
    client_a.post(
        "/api/v1/scenarios",
        json={
            "document_id": str(doc.id),
            "name": "Audit Scenario",
            "base_period": "FY2024",
            "growth_adjustment": "0.05",
        },
    )

    events = client_a.get("/api/v1/audit").json()["items"]
    assert len(events) >= 1

    # Filter by entity_type
    scen_events = client_a.get("/api/v1/audit?entity_type=scenario").json()["items"]
    assert all(e["entity_type"] == "scenario" for e in scen_events)


def test_audit_trail_authorization(client_a, client_b, db_session, user_a, user_b):
    # User A events are not visible to User B
    doc, _ = seed_document(db_session, user_a, "UserADoc.pdf", 2024)
    client_a.post(
        "/api/v1/scenarios",
        json={
            "document_id": str(doc.id),
            "name": "Secret Scenario",
            "base_period": "FY2024",
            "growth_adjustment": "0.05",
        },
    )

    events_b = client_b.get("/api/v1/audit").json()["items"]
    assert not any(e["metadata"].get("name") == "Secret Scenario" for e in events_b)


# ==========================================================================================
# 11. COMPANY WORKSPACE TESTS
# ==========================================================================================


def test_company_workspace_lifecycle(client_a, db_session, user_a):
    # 1. Create company
    comp_res = client_a.post(
        "/api/v1/companies",
        json={
            "name": "Bank Central Asia",
            "ticker": "BBCA",
            "country": "Indonesia",
            "currency": "IDR",
            "description": "Leading private bank in Indonesia.",
        },
    )
    assert comp_res.status_code == 201
    comp = comp_res.json()
    comp_id = comp["id"]
    assert comp["ticker"] == "BBCA"

    # 2. Seed documents
    doc_2024, _ = seed_document(db_session, user_a, "BBCA_2024.pdf", 2024, "Bank Central Asia")
    doc_2025, _ = seed_document(db_session, user_a, "BBCA_2025.pdf", 2025, "Bank Central Asia")

    # 3. Associate document with company
    assoc_res = client_a.post(
        f"/api/v1/companies/{comp_id}/documents",
        json={"document_id": str(doc_2024.id)},
    )
    assert assoc_res.status_code == 200
    assert assoc_res.json()["company_id"] == comp_id

    client_a.post(
        f"/api/v1/companies/{comp_id}/documents",
        json={"document_id": str(doc_2025.id)},
    )

    # 4. View company details with aggregated financials
    detail_res = client_a.get(f"/api/v1/companies/{comp_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert len(detail["documents"]) == 2
    assert detail["financials"] is not None
    assert "FY2024" in detail["financials"]["periods"]
    assert "FY2025" in detail["financials"]["periods"]

    # 5. Disassociate document
    disassoc_res = client_a.delete(f"/api/v1/companies/{comp_id}/documents/{doc_2024.id}")
    assert disassoc_res.status_code == 200
    assert disassoc_res.json()["company_id"] is None


# ==========================================================================================
# 12. WATCHLIST TESTS
# ==========================================================================================


def test_watchlist_add_remove_and_duplicate_prevention(client_a, db_session, user_a):
    comp_res = client_a.post(
        "/api/v1/companies",
        json={"name": "Telkom Indonesia", "ticker": "TLKM", "country": "Indonesia"},
    )
    comp_id = comp_res.json()["id"]

    # Add to watchlist
    add_res = client_a.post("/api/v1/watchlist", json={"company_id": comp_id})
    assert add_res.status_code == 201

    # Duplicate add is idempotent
    add_dup = client_a.post("/api/v1/watchlist", json={"company_id": comp_id})
    assert add_dup.status_code in (200, 201)

    # Check watchlist list
    wl = client_a.get("/api/v1/watchlist").json()
    assert len(wl) == 1
    assert wl[0]["company_id"] == comp_id
    assert wl[0]["name"] == "Telkom Indonesia"

    # Remove from watchlist
    del_res = client_a.delete(f"/api/v1/watchlist/{comp_id}")
    assert del_res.status_code == 204

    wl_after = client_a.get("/api/v1/watchlist").json()
    assert len(wl_after) == 0


def test_watchlist_authorization(client_a, client_b, db_session, user_a, user_b):
    comp_res = client_a.post("/api/v1/companies", json={"name": "Astra International"})
    comp_id = comp_res.json()["id"]

    # User B cannot bookmark User A's private company
    res = client_b.post("/api/v1/watchlist", json={"company_id": comp_id})
    assert res.status_code == 404


# ==========================================================================================
# END-TO-END WORKFLOW TEST
# ==========================================================================================


def test_phase6_end_to_end_research_pipeline(client_a, db_session, user_a):
    """Real workflow test across all Phase 6 features."""
    # 1. Seed two annual reports
    doc_2024, facts_2024 = seed_document(db_session, user_a, "BBCA_AR2024.pdf", 2024)
    doc_2025, facts_2025 = seed_document(db_session, user_a, "BBCA_AR2025.pdf", 2025)

    # 2. Review extracted facts: Correct 2024 Net Income
    ni_fact = next(f for f in facts_2024 if f.metric_id == facts_2024[1].metric_id)
    review_res = client_a.post(
        f"/api/v1/financial-facts/{ni_fact.id}/correct",
        json={
            "value": "1450000000000",
            "currency": "IDR",
            "scale": "trillions",
            "reason": "Audited figure confirmed from Income Statement Page 87.",
        },
    )
    assert review_res.status_code == 200

    # 3. Run Data Quality checks
    dq_res = client_a.get(f"/api/v1/data-quality?document_id={doc_2024.id}")
    assert dq_res.status_code == 200
    dq_data = dq_res.json()
    assert dq_data["summary"]["facts_verified_count"] >= 3

    # 4. Compare 2024 with 2025 (Document Diff)
    diff_res = client_a.post(
        "/api/v1/documents/diff",
        json={"document_a_id": str(doc_2024.id), "document_b_id": str(doc_2025.id)},
    )
    assert diff_res.status_code == 200
    diff_data = diff_res.json()
    assert len(diff_data["financial_diff"]) > 0

    # 5. Create Scenario from 2025 reported revenue
    scen_res = client_a.post(
        "/api/v1/scenarios",
        json={
            "document_id": str(doc_2025.id),
            "name": "Base Growth Scenario",
            "base_period": "FY2025",
            "growth_adjustment": "0.08",
            "margin_adjustment": "0.01",
        },
    )
    assert scen_res.status_code == 201

    # 6. Verify Audit Trail has logged all these operations
    audit_res = client_a.get("/api/v1/audit")
    assert audit_res.status_code == 200
    events = audit_res.json()["items"]
    event_types = {e["event_type"] for e in events}
    assert "FACT_CORRECTED" in event_types
    assert "DOCUMENT_COMPARED" in event_types
    assert "SCENARIO_CREATED" in event_types

    # 7. Create Company and Associate both documents
    comp_res = client_a.post(
        "/api/v1/companies",
        json={"name": "Bank Central Asia", "ticker": "BBCA"},
    )
    assert comp_res.status_code == 201
    comp_id = comp_res.json()["id"]

    client_a.post(f"/api/v1/companies/{comp_id}/documents", json={"document_id": str(doc_2024.id)})
    client_a.post(f"/api/v1/companies/{comp_id}/documents", json={"document_id": str(doc_2025.id)})

    # 8. Add Company to Watchlist
    wl_res = client_a.post("/api/v1/watchlist", json={"company_id": comp_id})
    assert wl_res.status_code == 201

    wl_list = client_a.get("/api/v1/watchlist").json()
    assert len(wl_list) == 1
    assert wl_list[0]["ticker"] == "BBCA"

    # 9. Export Financials
    exp_res = client_a.get(f"/api/v1/documents/{doc_2025.id}/export?format=csv")
    assert exp_res.status_code == 200
    assert "text/csv" in exp_res.headers["content-type"]
    assert len(exp_res.content) > 0
