"""Company Workspace Management (PRD Phase 6 §11).

Organizes multi-document financial research at the company level.
Aggregates canonical financial facts, timelines, and data quality across
associated documents without duplicating facts.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_audit_event
from app.auth import CurrentUserId
from app.documents import (
    DbSession,
    DocumentOut,
    _owned_document,
)
from app.errors import ApiError
from app.financials import Financials, load_financials
from app.models import (
    Company,
    Document,
    DocumentStatus,
    Scenario,
    WatchlistEntry,
)

router = APIRouter(prefix="/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    ticker: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: str | None = None


class CompanyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    ticker: str | None = Field(default=None, max_length=20)
    country: str | None = Field(default=None, max_length=50)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    description: str | None = None


class CompanySummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    ticker: str | None
    country: str | None
    currency: str | None
    description: str | None
    document_count: int
    latest_period: str | None
    is_in_watchlist: bool
    created_at: datetime
    updated_at: datetime


class AssociateDocumentRequest(BaseModel):
    document_id: uuid.UUID


class CompanyDetailOut(BaseModel):
    id: uuid.UUID
    name: str
    ticker: str | None
    country: str | None
    currency: str | None
    description: str | None
    documents: list[DocumentOut]
    latest_period: str | None
    is_in_watchlist: bool
    financials: Financials | None
    scenario_count: int
    created_at: datetime
    updated_at: datetime


def _owned_company(session: Session, user_id: uuid.UUID, company_id: uuid.UUID) -> Company:
    company = session.scalar(
        select(Company).where(Company.id == company_id, Company.user_id == user_id)
    )
    if not company:
        raise ApiError(404, "not_found", "Company not found")
    return company


@router.post("", response_model=CompanySummaryOut, status_code=201)
def create_company(
    body: CompanyCreate, user_id: CurrentUserId, session: DbSession
) -> CompanySummaryOut:
    """Create a company research workspace."""
    clean_name = " ".join(body.name.split())
    existing = session.scalar(
        select(Company).where(
            Company.user_id == user_id,
            func.lower(Company.name) == clean_name.lower(),
        )
    )
    if existing:
        raise ApiError(409, "company_exists", f"Company '{clean_name}' already exists")

    company = Company(
        user_id=user_id,
        name=clean_name,
        ticker=body.ticker.upper() if body.ticker else None,
        country=body.country,
        currency=body.currency.upper() if body.currency else None,
        description=body.description,
    )
    session.add(company)
    session.flush()

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="COMPANY_CREATED",
        entity_type="company",
        entity_id=str(company.id),
        metadata={"name": company.name, "ticker": company.ticker},
        reason=f"Created company workspace '{company.name}'",
    )
    session.commit()

    return CompanySummaryOut(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        country=company.country,
        currency=company.currency,
        description=company.description,
        document_count=0,
        latest_period=None,
        is_in_watchlist=False,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


@router.get("", response_model=list[CompanySummaryOut])
def list_companies(user_id: CurrentUserId, session: DbSession) -> list[CompanySummaryOut]:
    """List all companies owned by the user."""
    companies = list(
        session.scalars(
            select(Company).where(Company.user_id == user_id).order_by(Company.name)
        ).all()
    )
    watchlist_ids = set(
        session.scalars(
            select(WatchlistEntry.company_id).where(WatchlistEntry.user_id == user_id)
        ).all()
    )

    items: list[CompanySummaryOut] = []
    for c in companies:
        docs = list(
            session.scalars(
                select(Document).where(Document.company_id == c.id, Document.user_id == user_id)
            ).all()
        )
        # Find latest period if documents exist
        latest_period = None
        if docs:
            ready_docs = [d for d in docs if d.status == DocumentStatus.READY]
            if ready_docs:
                try:
                    fin = load_financials(session, user_id, ready_docs[0].id, scope="company")
                    latest_period = fin.periods[-1] if fin.periods else None
                except Exception:
                    latest_period = None

        items.append(
            CompanySummaryOut(
                id=c.id,
                name=c.name,
                ticker=c.ticker,
                country=c.country,
                currency=c.currency,
                description=c.description,
                document_count=len(docs),
                latest_period=latest_period,
                is_in_watchlist=c.id in watchlist_ids,
                created_at=c.created_at,
                updated_at=c.updated_at,
            )
        )
    return items


@router.get("/{company_id}", response_model=CompanyDetailOut)
def get_company(
    company_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> CompanyDetailOut:
    """Retrieve full company workspace details, timeline, and financials."""
    company = _owned_company(session, user_id, company_id)
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.company_id == company.id, Document.user_id == user_id)
            .order_by(Document.fiscal_year.desc(), Document.created_at.desc())
        ).all()
    )

    is_in_watchlist = bool(
        session.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == user_id, WatchlistEntry.company_id == company.id
            )
        )
    )

    scenarios_count = (
        session.scalar(
            select(func.count(Scenario.id)).where(
                Scenario.user_id == user_id, Scenario.company_id == company.id
            )
        )
        or 0
    )

    financials_data: Financials | None = None
    latest_period: str | None = None

    ready_docs = [d for d in documents if d.status == DocumentStatus.READY]
    if ready_docs:
        try:
            financials_data = load_financials(session, user_id, ready_docs[0].id, scope="company")
            latest_period = financials_data.periods[-1] if financials_data.periods else None
        except Exception:
            financials_data = None

    return CompanyDetailOut(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        country=company.country,
        currency=company.currency,
        description=company.description,
        documents=[DocumentOut.model_validate(d) for d in documents],
        latest_period=latest_period,
        is_in_watchlist=is_in_watchlist,
        financials=financials_data,
        scenario_count=scenarios_count,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


@router.patch("/{company_id}", response_model=CompanySummaryOut)
def update_company(
    company_id: uuid.UUID,
    body: CompanyUpdate,
    user_id: CurrentUserId,
    session: DbSession,
) -> CompanySummaryOut:
    """Update company metadata."""
    company = _owned_company(session, user_id, company_id)
    before_dict = {"name": company.name, "ticker": company.ticker, "country": company.country}

    if body.name is not None:
        clean_name = " ".join(body.name.split())
        company.name = clean_name
    if body.ticker is not None:
        company.ticker = body.ticker.upper() if body.ticker else None
    if body.country is not None:
        company.country = body.country
    if body.currency is not None:
        company.currency = body.currency.upper() if body.currency else None
    if body.description is not None:
        company.description = body.description

    company.updated_at = datetime.now()
    after_dict = {"name": company.name, "ticker": company.ticker, "country": company.country}

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="COMPANY_UPDATED",
        entity_type="company",
        entity_id=str(company.id),
        before=before_dict,
        after=after_dict,
        reason=f"Updated company '{company.name}'",
    )
    session.commit()

    doc_count = (
        session.scalar(select(func.count(Document.id)).where(Document.company_id == company.id))
        or 0
    )
    is_in_watchlist = bool(
        session.scalar(
            select(WatchlistEntry).where(
                WatchlistEntry.user_id == user_id, WatchlistEntry.company_id == company.id
            )
        )
    )

    return CompanySummaryOut(
        id=company.id,
        name=company.name,
        ticker=company.ticker,
        country=company.country,
        currency=company.currency,
        description=company.description,
        document_count=doc_count,
        latest_period=None,
        is_in_watchlist=is_in_watchlist,
        created_at=company.created_at,
        updated_at=company.updated_at,
    )


@router.delete("/{company_id}", status_code=204)
def delete_company(company_id: uuid.UUID, user_id: CurrentUserId, session: DbSession) -> None:
    """Delete company workspace. Associated documents are detached, not deleted."""
    company = _owned_company(session, user_id, company_id)
    # Detach documents
    session.query(Document).filter(
        Document.company_id == company.id, Document.user_id == user_id
    ).update({"company_id": None})

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="COMPANY_DELETED",
        entity_type="company",
        entity_id=str(company.id),
        metadata={"name": company.name},
        reason=f"Deleted company '{company.name}'",
    )
    session.delete(company)
    session.commit()


@router.post("/{company_id}/documents", response_model=DocumentOut)
def associate_document(
    company_id: uuid.UUID,
    body: AssociateDocumentRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> DocumentOut:
    """Associate a document with this company workspace."""
    company = _owned_company(session, user_id, company_id)
    doc = _owned_document(session, user_id, body.document_id, lock=True)

    doc.company_id = company.id
    doc.company_name = company.name
    session.commit()

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="DOCUMENT_PROCESSED",
        entity_type="document",
        entity_id=str(doc.id),
        metadata={"company_id": str(company.id), "company_name": company.name},
        reason=f"Associated document '{doc.filename}' with company '{company.name}'",
    )
    session.commit()

    return DocumentOut.model_validate(doc)


@router.delete("/{company_id}/documents/{document_id}", response_model=DocumentOut)
def disassociate_document(
    company_id: uuid.UUID,
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
) -> DocumentOut:
    """Remove document from company workspace (document remains as standalone)."""
    _owned_company(session, user_id, company_id)
    doc = _owned_document(session, user_id, document_id, lock=True)

    doc.company_id = None
    session.commit()

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="DOCUMENT_PROCESSED",
        entity_type="document",
        entity_id=str(doc.id),
        metadata={"disassociated_from_company_id": str(company_id)},
        reason=f"Disassociated document '{doc.filename}' from company workspace",
    )
    session.commit()

    return DocumentOut.model_validate(doc)
