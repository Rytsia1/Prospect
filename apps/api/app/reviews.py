"""Extraction Review Queue and Fact Correction (PRD Phase 6 §7).

Allows users to review, accept, correct, or reject extracted financial facts.
Preserves full historical audit records of corrections without data loss.
Validates all user-supplied values.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit_event
from app.auth import CurrentUserId
from app.documents import (
    DbSession,
    DecimalStr,
    EvidenceOut,
    Paragraph,
    ShortLine,
)
from app.errors import ApiError
from app.extraction import SCALES
from app.models import (
    Document,
    DocumentPage,
    DocumentSection,
    Evidence,
    ExtractionReview,
    FactStatus,
    FinancialFact,
    FinancialMetric,
    PeriodType,
)

router = APIRouter(prefix="/financial-facts", tags=["review"])


class ReviewFactOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_filename: str
    metric: str
    metric_name: str
    value: DecimalStr
    currency: str | None
    scale: str
    original_text: str
    period_type: PeriodType
    period_label: str
    fiscal_year: int | None
    confidence: DecimalStr
    confidence_tier: Literal["high", "medium", "low"]
    status: FactStatus
    review_reasons: list[str]
    extraction_method: str
    evidence: EvidenceOut


class ReviewList(BaseModel):
    items: list[ReviewFactOut]
    total_count: int


class ReviewHistoryOut(BaseModel):
    id: uuid.UUID
    fact_id: uuid.UUID
    document_id: uuid.UUID
    user_id: uuid.UUID
    action: str
    original_value: DecimalStr
    original_currency: str | None
    original_scale: str
    original_period_type: str
    original_period_label: str
    corrected_value: DecimalStr | None
    corrected_currency: str | None
    corrected_scale: str | None
    corrected_period_type: str | None
    corrected_period_label: str | None
    reason: str | None
    created_at: datetime


class AcceptRequest(BaseModel):
    reason: Paragraph | None = None


class CorrectRequest(BaseModel):
    # Currency units: whole values up to 10^24, at most 6 decimal places. The database column is
    # unconstrained NUMERIC, so the bound lives here.
    value: Decimal = Field(
        max_digits=30, decimal_places=6, description="Corrected value in currency units"
    )
    currency: Annotated[ShortLine, Field(min_length=3, max_length=3)] | None = None
    scale: ShortLine | None = Field(default=None, description="Source unit scale: units, millions")
    period_type: PeriodType | None = None
    period_label: ShortLine | None = None
    metric_key: ShortLine | None = Field(default=None, description="Optional reassigned metric")
    reason: Annotated[Paragraph, Field(min_length=3, description="Reason for correction")]


class RejectRequest(BaseModel):
    reason: Annotated[Paragraph, Field(min_length=3, description="Reason for rejection")]


def _confidence_tier(conf: Decimal) -> Literal["high", "medium", "low"]:
    if conf >= Decimal("0.8"):
        return "high"
    if conf >= Decimal("0.5"):
        return "medium"
    return "low"


def _owned_fact(
    session: Session, user_id: uuid.UUID, fact_id: uuid.UUID
) -> tuple[FinancialFact, Document]:
    fact = session.scalar(select(FinancialFact).where(FinancialFact.id == fact_id))
    if fact is None:
        raise ApiError(404, "not_found", "Financial fact not found")
    doc = session.scalar(
        select(Document).where(Document.id == fact.document_id, Document.user_id == user_id)
    )
    if doc is None:
        raise ApiError(404, "not_found", "Financial fact not found")
    return fact, doc


@router.get("/review", response_model=ReviewList)
def list_facts_for_review(
    user_id: CurrentUserId,
    session: DbSession,
    status: Annotated[
        Literal[
            "all", "needs_review", "pending", "pending_review", "accepted", "corrected", "rejected"
        ]
        | None,
        Query(),
    ] = None,
    confidence_tier: Annotated[Literal["high", "medium", "low"] | None, Query()] = None,
    document_id: Annotated[uuid.UUID | None, Query()] = None,
    metric: Annotated[str | None, Query(max_length=64)] = None,
    period: Annotated[str | None, Query(max_length=40)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ReviewList:
    """Retrieve facts for review with filtering across documents owned by user."""
    query = (
        select(
            FinancialFact,
            FinancialMetric,
            Evidence,
            DocumentPage.page_metadata["label"].astext,  # the label only, never the page text
            DocumentSection,
            Document,
        )
        .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
        .join(Evidence, Evidence.id == FinancialFact.evidence_id)
        .join(DocumentPage, DocumentPage.id == Evidence.page_id)
        .join(DocumentSection, DocumentSection.id == Evidence.section_id)
        .join(Document, Document.id == FinancialFact.document_id)
        .where(Document.user_id == user_id)
    )

    if document_id:
        query = query.where(FinancialFact.document_id == document_id)
    if metric:
        query = query.where(FinancialMetric.key == metric)
    if period:
        query = query.where(FinancialFact.period_label == period)

    if status and status.lower() != "all":
        status_clean = status.lower()
        if status_clean in ("needs_review", "pending", "pending_review"):
            query = query.where(FinancialFact.status == FactStatus.NEEDS_REVIEW)
        elif status_clean == "accepted":
            query = query.where(FinancialFact.status == FactStatus.ACCEPTED)
        elif status_clean == "corrected":
            query = query.where(FinancialFact.status == FactStatus.CORRECTED)
        elif status_clean == "rejected":
            query = query.where(FinancialFact.status == FactStatus.REJECTED)

    if confidence_tier:
        if confidence_tier == "high":
            query = query.where(FinancialFact.confidence >= Decimal("0.8"))
        elif confidence_tier == "medium":
            query = query.where(
                FinancialFact.confidence >= Decimal("0.5"),
                FinancialFact.confidence < Decimal("0.8"),
            )
        elif confidence_tier == "low":
            query = query.where(FinancialFact.confidence < Decimal("0.5"))

    query = query.order_by(FinancialFact.created_at.desc()).limit(limit)
    rows = session.execute(query).all()

    items = [
        ReviewFactOut(
            id=fact.id,
            document_id=fact.document_id,
            document_filename=doc.filename,
            metric=metric_row.key,
            metric_name=metric_row.name,
            value=fact.value_numeric,
            currency=fact.currency,
            scale=fact.scale,
            original_text=fact.original_text,
            period_type=fact.period_type,
            period_label=fact.period_label,
            fiscal_year=fact.fiscal_year,
            confidence=fact.confidence,
            confidence_tier=_confidence_tier(fact.confidence),
            status=fact.status,
            review_reasons=fact.review_reasons,
            extraction_method=fact.extraction_method,
            evidence=EvidenceOut(
                id=evidence.id,
                page_number=evidence.page_number,
                page_label=page_label,
                section_title=section.title,
                chunk_id=evidence.chunk_id,
                kind=evidence.evidence_type.value,
                content=evidence.content,
                header=evidence.locator.get("header"),
                unit=evidence.locator.get("unit"),
            ),
        )
        for fact, metric_row, evidence, page_label, section, doc in rows
    ]
    return ReviewList(items=items, total_count=len(items))


@router.post("/{fact_id}/accept", response_model=ReviewFactOut)
def accept_fact(
    fact_id: uuid.UUID,
    body: AcceptRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ReviewFactOut:
    """Accept an extracted fact as authoritative."""
    fact, doc = _owned_fact(session, user_id, fact_id)
    if fact.currency is None:
        raise ApiError(422, "missing_currency", "Cannot accept fact without a stated currency")

    before_status = fact.status.value
    fact.status = FactStatus.ACCEPTED
    session.add(
        ExtractionReview(
            document_id=doc.id,
            fact_id=fact.id,
            user_id=user_id,
            action="accepted",
            original_value=fact.value_numeric,
            original_currency=fact.currency,
            original_scale=fact.scale,
            original_period_type=fact.period_type.value,
            original_period_label=fact.period_label,
            reason=body.reason or "Accepted by reviewer",
        )
    )
    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="FACT_ACCEPTED",
        entity_type="financial_fact",
        entity_id=str(fact.id),
        metadata={"document_id": str(doc.id), "period": fact.period_label},
        before={"status": before_status},
        after={"status": "accepted"},
        reason=body.reason or "Accepted fact as authoritative",
    )
    session.commit()

    # Fetch with relationships for response
    row = session.execute(
        select(FinancialFact, FinancialMetric, Evidence, DocumentPage, DocumentSection)
        .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
        .join(Evidence, Evidence.id == FinancialFact.evidence_id)
        .join(DocumentPage, DocumentPage.id == Evidence.page_id)
        .join(DocumentSection, DocumentSection.id == Evidence.section_id)
        .where(FinancialFact.id == fact.id)
    ).one()
    f, m, e, p, s = row
    return ReviewFactOut(
        id=f.id,
        document_id=f.document_id,
        document_filename=doc.filename,
        metric=m.key,
        metric_name=m.name,
        value=f.value_numeric,
        currency=f.currency,
        scale=f.scale,
        original_text=f.original_text,
        period_type=f.period_type,
        period_label=f.period_label,
        fiscal_year=f.fiscal_year,
        confidence=f.confidence,
        confidence_tier=_confidence_tier(f.confidence),
        status=f.status,
        review_reasons=f.review_reasons,
        extraction_method=f.extraction_method,
        evidence=EvidenceOut(
            id=e.id,
            page_number=e.page_number,
            page_label=p.page_metadata.get("label"),
            section_title=s.title,
            chunk_id=e.chunk_id,
            kind=e.evidence_type.value,
            content=e.content,
            header=e.locator.get("header"),
            unit=e.locator.get("unit"),
        ),
    )


@router.post("/{fact_id}/correct", response_model=ReviewFactOut)
def correct_fact(
    fact_id: uuid.UUID,
    body: CorrectRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ReviewFactOut:
    """Correct an extracted fact's value, currency, scale, or period. Preserves history."""
    fact, doc = _owned_fact(session, user_id, fact_id)

    # Validate scale if provided
    new_scale = body.scale or fact.scale
    if new_scale not in SCALES:
        raise ApiError(
            422,
            "invalid_scale",
            f"Invalid scale '{new_scale}'. Supported scales: {list(SCALES.keys())}",
        )

    # Validate currency
    new_currency = body.currency.upper() if body.currency else fact.currency
    if not new_currency or len(new_currency) != 3:
        raise ApiError(
            422, "invalid_currency", "Currency must be a 3-letter ISO code (e.g. IDR, USD)"
        )

    # Validate metric if reclassifying
    new_metric_id = fact.metric_id
    if body.metric_key:
        metric_obj = session.scalar(
            select(FinancialMetric).where(FinancialMetric.key == body.metric_key)
        )
        if not metric_obj:
            raise ApiError(422, "invalid_metric", f"Unknown metric key: {body.metric_key}")
        new_metric_id = metric_obj.id

    new_period_type = body.period_type or fact.period_type
    new_period_label = body.period_label or fact.period_label

    # Record history
    review_record = ExtractionReview(
        document_id=doc.id,
        fact_id=fact.id,
        user_id=user_id,
        action="corrected",
        original_value=fact.value_numeric,
        original_currency=fact.currency,
        original_scale=fact.scale,
        original_period_type=fact.period_type.value,
        original_period_label=fact.period_label,
        corrected_value=body.value,
        corrected_currency=new_currency,
        corrected_scale=new_scale,
        corrected_period_type=new_period_type.value,
        corrected_period_label=new_period_label,
        reason=body.reason,
    )
    session.add(review_record)

    before_dict = {
        "value": str(fact.value_numeric),
        "currency": fact.currency,
        "scale": fact.scale,
        "period_label": fact.period_label,
        "status": fact.status.value,
    }

    # Update fact
    fact.value_numeric = body.value
    fact.currency = new_currency
    fact.scale = new_scale
    fact.period_type = new_period_type
    fact.period_label = new_period_label
    fact.metric_id = new_metric_id
    fact.status = FactStatus.CORRECTED
    fact.extraction_method = "manual"

    after_dict = {
        "value": str(fact.value_numeric),
        "currency": fact.currency,
        "scale": fact.scale,
        "period_label": fact.period_label,
        "status": "corrected",
    }

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="FACT_CORRECTED",
        entity_type="financial_fact",
        entity_id=str(fact.id),
        metadata={"document_id": str(doc.id)},
        before=before_dict,
        after=after_dict,
        reason=body.reason,
    )
    session.commit()

    row = session.execute(
        select(FinancialFact, FinancialMetric, Evidence, DocumentPage, DocumentSection)
        .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
        .join(Evidence, Evidence.id == FinancialFact.evidence_id)
        .join(DocumentPage, DocumentPage.id == Evidence.page_id)
        .join(DocumentSection, DocumentSection.id == Evidence.section_id)
        .where(FinancialFact.id == fact.id)
    ).one()
    f, m, e, p, s = row
    return ReviewFactOut(
        id=f.id,
        document_id=f.document_id,
        document_filename=doc.filename,
        metric=m.key,
        metric_name=m.name,
        value=f.value_numeric,
        currency=f.currency,
        scale=f.scale,
        original_text=f.original_text,
        period_type=f.period_type,
        period_label=f.period_label,
        fiscal_year=f.fiscal_year,
        confidence=f.confidence,
        confidence_tier=_confidence_tier(f.confidence),
        status=f.status,
        review_reasons=f.review_reasons,
        extraction_method=f.extraction_method,
        evidence=EvidenceOut(
            id=e.id,
            page_number=e.page_number,
            page_label=p.page_metadata.get("label"),
            section_title=s.title,
            chunk_id=e.chunk_id,
            kind=e.evidence_type.value,
            content=e.content,
            header=e.locator.get("header"),
            unit=e.locator.get("unit"),
        ),
    )


@router.post("/{fact_id}/reject", response_model=ReviewFactOut)
def reject_fact(
    fact_id: uuid.UUID,
    body: RejectRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ReviewFactOut:
    """Reject an extracted fact. Keeps the record for audit but marks it as rejected."""
    fact, doc = _owned_fact(session, user_id, fact_id)
    before_status = fact.status.value
    fact.status = FactStatus.REJECTED

    session.add(
        ExtractionReview(
            document_id=doc.id,
            fact_id=fact.id,
            user_id=user_id,
            action="rejected",
            original_value=fact.value_numeric,
            original_currency=fact.currency,
            original_scale=fact.scale,
            original_period_type=fact.period_type.value,
            original_period_label=fact.period_label,
            reason=body.reason,
        )
    )
    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="FACT_REJECTED",
        entity_type="financial_fact",
        entity_id=str(fact.id),
        metadata={"document_id": str(doc.id)},
        before={"status": before_status},
        after={"status": "rejected"},
        reason=body.reason,
    )
    session.commit()

    row = session.execute(
        select(FinancialFact, FinancialMetric, Evidence, DocumentPage, DocumentSection)
        .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
        .join(Evidence, Evidence.id == FinancialFact.evidence_id)
        .join(DocumentPage, DocumentPage.id == Evidence.page_id)
        .join(DocumentSection, DocumentSection.id == Evidence.section_id)
        .where(FinancialFact.id == fact.id)
    ).one()
    f, m, e, p, s = row
    return ReviewFactOut(
        id=f.id,
        document_id=f.document_id,
        document_filename=doc.filename,
        metric=m.key,
        metric_name=m.name,
        value=f.value_numeric,
        currency=f.currency,
        scale=f.scale,
        original_text=f.original_text,
        period_type=f.period_type,
        period_label=f.period_label,
        fiscal_year=f.fiscal_year,
        confidence=f.confidence,
        confidence_tier=_confidence_tier(f.confidence),
        status=f.status,
        review_reasons=f.review_reasons,
        extraction_method=f.extraction_method,
        evidence=EvidenceOut(
            id=e.id,
            page_number=e.page_number,
            page_label=p.page_metadata.get("label"),
            section_title=s.title,
            chunk_id=e.chunk_id,
            kind=e.evidence_type.value,
            content=e.content,
            header=e.locator.get("header"),
            unit=e.locator.get("unit"),
        ),
    )


@router.get("/{fact_id}/history", response_model=list[ReviewHistoryOut])
def get_fact_review_history(
    fact_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> list[ReviewHistoryOut]:
    """Retrieve full audit history of reviews and corrections for a fact."""
    _owned_fact(session, user_id, fact_id)
    reviews = session.scalars(
        select(ExtractionReview)
        .where(ExtractionReview.fact_id == fact_id)
        .order_by(ExtractionReview.created_at.desc())
    ).all()
    return [
        ReviewHistoryOut(
            id=r.id,
            fact_id=r.fact_id,
            document_id=r.document_id,
            user_id=r.user_id,
            action=r.action,
            original_value=r.original_value,
            original_currency=r.original_currency,
            original_scale=r.original_scale,
            original_period_type=r.original_period_type,
            original_period_label=r.original_period_label,
            corrected_value=r.corrected_value,
            corrected_currency=r.corrected_currency,
            corrected_scale=r.corrected_scale,
            corrected_period_type=r.corrected_period_type,
            corrected_period_label=r.corrected_period_label,
            reason=r.reason,
            created_at=r.created_at,
        )
        for r in reviews
    ]
