"""Research workspace endpoints: timeline/dashboard, evidence explorer, export.

All three read the canonical financial facts through documents._facts and derive everything on
read (app/workspace.py, app/analytics.py); nothing is copied into view-specific tables. The export
serializes the same payload the UI shows, so exported values match displayed values.
"""

import uuid
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app import exports
from app.analytics import FORMULAS, FactInput, Result
from app.auth import CurrentUserId, limit_user
from app.config import get_settings
from app.documents import DbSession, DecimalStr, FactOut, _facts, _owned_document
from app.errors import ApiError
from app.logs import audit_event, security_event
from app.models import Document, DocumentStatus, PeriodType
from app.workspace import METRIC_NAMES, TIMELINE_METRICS, SourceFact, build

router = APIRouter(prefix="/documents", tags=["financials"])
Scope = Literal["document", "company"]


class DocumentRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    fiscal_year: int | None
    company_name: str | None


class MetricRef(BaseModel):
    key: str
    name: str


class ResultOut(BaseModel):
    """A deterministic calculation computed on read from the facts in scope."""

    metric: str
    name: str
    formula_key: str
    formula: str
    period: str  # normalized period (FY2025, or a balance date without an established year)
    period_type: PeriodType
    period_label: str
    status: Literal["calculated", "not_possible"]
    value: DecimalStr | None  # plain ratio, full precision
    unit: Literal["percent", "times"]
    reason_code: str | None
    reason: str | None
    notes: list[str]
    input_fact_ids: list[uuid.UUID]  # look up in Financials.facts for values and evidence


class CellOut(BaseModel):
    metric: str
    period: str
    status: Literal["value", "conflict", "needs_review"]
    fact_ids: list[uuid.UUID]  # every source document's fact for this metric and period
    primary_fact_id: uuid.UUID | None  # the value shown; null for conflicts and review items
    change: ResultOut | None  # year-over-year, when the earlier period exists


class ReconciliationOut(BaseModel):
    check: Literal["balance_sheet"] = "balance_sheet"
    formula: str = "total_assets − (total_liabilities + equity)"
    period: str
    status: Literal["BALANCED", "ROUNDING_DIFFERENCE", "MISMATCH", "INSUFFICIENT_DATA"]
    fact_ids: dict[str, uuid.UUID]
    liabilities_plus_equity: DecimalStr | None
    difference: DecimalStr | None
    tolerance: DecimalStr | None
    currency: str | None
    problems: list[str]


class QualityOut(BaseModel):
    period: str
    level: Literal["ok", "warning", "info"]
    message: str
    metric: str | None


class Financials(BaseModel):
    scope: Scope
    company_name: str | None  # null: the document has no company, so scope is this document
    documents: list[DocumentRef]
    metrics: list[MetricRef]  # timeline rows, in display order
    periods: list[str]  # oldest first
    period_basis: dict[str, str]  # fiscal_year | fiscal_year_end | date
    facts: list[FactOut]  # every fact in scope, with evidence (including needs_review)
    fact_periods: dict[uuid.UUID, str]  # fact → normalized period (annual and balance facts)
    cells: list[CellOut]
    calculations: list[ResultOut]
    reconciliations: list[ReconciliationOut]
    quality: list[QualityOut]


class EvidenceView(BaseModel):
    document: DocumentRef
    fact: FactOut


def _result_out(period: str, r: Result) -> ResultOut:
    _, name, formula, _ = FORMULAS[r.formula_key]
    return ResultOut(
        metric=r.metric,
        name=name,
        formula_key=r.formula_key,
        formula=formula,
        period=period,
        period_type=PeriodType(r.period_type),
        period_label=r.period_label,
        status=r.status,
        value=r.value,
        unit=r.unit,
        reason_code=r.reason_code,
        reason=r.reason,
        notes=list(r.notes),
        input_fact_ids=list(r.input_ids),
    )


def _scope_documents(
    session: Session, user_id: uuid.UUID, document: Document, scope: Scope
) -> list[Document]:
    """The document alone, or every READY report of the same company owned by the same user.

    A document linked to a company workspace groups by that company's id only, so a same-named
    report that was never linked (or another company that happens to share the name) is never
    merged in. An unlinked document groups by its exact normalized label among unlinked ones:
    "Company A" and "Company A Inc." stay apart. Ownership comes first in either case.
    """
    if scope == "document" or not document.company_name:
        return [document]
    same_company = (
        Document.company_id == document.company_id
        if document.company_id
        else and_(
            Document.company_id.is_(None),
            func.lower(Document.company_name) == document.company_name.lower(),
        )
    )
    cap = get_settings().financials_max_documents
    documents = list(
        session.scalars(
            select(Document)
            .where(
                Document.user_id == user_id,  # ownership before any company-scoped query
                same_company,
                or_(Document.id == document.id, Document.status == DocumentStatus.READY),
            )
            .order_by(Document.fiscal_year, Document.created_at)
            .limit(cap + 1)
        )
    )
    if len(documents) > cap:
        security_event("financial_data_limit_exceeded", documents=len(documents), limit=cap)
        raise ApiError(
            413,
            "financial_data_too_large",
            f"This company has more than {cap} reports. Open them individually.",
        )
    return documents


def load_financials(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID, scope: Scope
) -> Financials:
    document = _owned_document(session, user_id, document_id)
    documents = _scope_documents(session, user_id, document, scope)
    facts = _facts(session, *(d.id for d in documents))  # every id belongs to this user
    sources = [
        SourceFact(
            FactInput(
                f.id,
                f.metric,
                f.value,
                f.currency or "",
                f.period_type.value,
                f.period_label,
                f.period_end,
                f.fiscal_year,
            ),
            f.document_id,
            "accepted" if f.status.value in ("accepted", "corrected") else "needs_review",
            f.scale,
        )
        for f in facts
    ]
    settings = get_settings()
    view = build(
        sources,
        settings.reconciliation_rounding_units,
        settings.reconciliation_relative_tolerance,
    )
    return Financials(
        scope=scope if document.company_name else "document",
        company_name=document.company_name,
        documents=[DocumentRef.model_validate(d) for d in documents],
        metrics=[MetricRef(key=m, name=METRIC_NAMES[m]) for m in TIMELINE_METRICS],
        periods=view.periods,
        period_basis=view.period_basis,
        facts=facts,
        fact_periods=view.fact_periods,
        cells=[
            CellOut(
                metric=c.metric,
                period=c.period,
                status=c.status,
                fact_ids=c.fact_ids,
                primary_fact_id=c.primary_fact_id,
                change=_result_out(c.period, c.change) if c.change else None,
            )
            for c in view.cells
        ],
        calculations=[_result_out(p, r) for p, r in view.calculations],
        reconciliations=[
            ReconciliationOut(
                period=r.period,
                status=r.status,
                fact_ids=r.fact_ids,
                liabilities_plus_equity=r.liabilities_plus_equity,
                difference=r.difference,
                tolerance=r.tolerance,
                currency=r.currency,
                problems=r.problems,
            )
            for r in view.reconciliations
        ],
        quality=[
            QualityOut(period=q.period, level=q.level, message=q.message, metric=q.metric)
            for q in view.quality
        ],
    )


@router.get("/{document_id}/financials", dependencies=[limit_user("financials")])
def get_financials(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
    scope: Scope = "document",
) -> Financials:
    """Timeline, dashboard, reconciliation and data quality for a document or its company."""
    return load_financials(session, user_id, document_id, scope)


@router.get("/{document_id}/evidence/{evidence_id}")
def get_evidence(
    document_id: uuid.UUID, evidence_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> EvidenceView:
    """One fact and its source, for the evidence explorer's deep link."""
    document = _owned_document(session, user_id, document_id)
    fact = next(iter(_facts(session, document_id, evidence_id=evidence_id, limit=1)), None)
    if fact is None:
        raise ApiError(404, "not_found", "Evidence not found")
    return EvidenceView(document=DocumentRef.model_validate(document), fact=fact)


def _too_large(request: Request, reason: str, size: int, limit: int) -> ApiError:
    security_event("export_limit_exceeded", request, reason=reason, size=size, limit=limit)
    audit_event("export_failed", request, result="rejected", reason=f"too many {reason}")
    return ApiError(
        413,
        "export_too_large",
        "Export exceeds the maximum allowed size. Select fewer periods or metrics; larger "
        "exports need asynchronous processing, which is not available yet.",
    )


@router.get("/{document_id}/export", dependencies=[limit_user("export")])
def export_financials(
    request: Request,
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
    format: Literal["csv", "json", "xlsx"] = "csv",
    scope: Scope = "document",
    periods: Annotated[list[str] | None, Query()] = None,
    metrics: Annotated[list[str] | None, Query()] = None,
) -> Response:
    """Facts, calculations, evidence and reconciliation, filtered, as CSV, JSON or XLSX."""
    settings = get_settings()
    view = load_financials(session, user_id, document_id, scope)  # ownership checked here
    tables = exports.tables(view, set(periods or []), set(metrics or []))
    # Bounded before serializing: never build an oversized file, never silently truncate one.
    records = sum(len(rows) for _, rows in tables.values())
    if records > settings.export_max_records:
        raise _too_large(request, "records", records, settings.export_max_records)
    body, media_type = exports.serialize(tables, view, format, datetime.now(UTC))
    if len(body) > settings.export_max_bytes:
        raise _too_large(request, "bytes", len(body), settings.export_max_bytes)
    audit_event(
        "export_created",
        request,
        entity_id=document_id,
        format=format,
        scope=view.scope,
        records=records,
        documents=len(view.documents),
    )
    stem = view.company_name if view.scope == "company" else view.documents[0].filename
    name = f"prospect-{(stem or 'export').rsplit('.pdf', 1)[0]}.{format}"
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in name)
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )
