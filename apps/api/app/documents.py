"""Document upload + metadata endpoints (docs/API_SPEC.yaml, docs/DEPLOYMENT.md §4).

Upload flow: POST /documents (signed PUT URL) → browser PUTs the PDF to private storage →
POST /documents/{id}/complete verifies the stored bytes server-side and queues processing.
"""

import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import quotas
from app.analytics import FORMULAS, INPUT_ORDER, METRIC_ORDER
from app.auth import CurrentUserId, limit_user
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.logs import security_event
from app.models import (
    Calculation,
    CalculationInput,
    CalculationStatus,
    Document,
    DocumentPage,
    DocumentSection,
    DocumentStatus,
    DocumentType,
    Evidence,
    FactStatus,
    FinancialFact,
    FinancialMetric,
    PageExtractionStatus,
    PeriodType,
    ProcessingJob,
)
from app.models import (
    DocumentSection as SectionRow,
)
from app.storage import ObjectStorage, get_storage

PDF_MIME = "application/pdf"
PDF_MAGIC = b"%PDF-"
PDF_HEADER_WINDOW = 1024  # PDF readers accept the header anywhere in the first 1 KiB

router = APIRouter(prefix="/documents", tags=["documents"])
DbSession = Annotated[Session, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]


def _company(name: str | None) -> str | None:
    """Collapse whitespace; blank means no company."""
    return (" ".join(name.split()) or None) if name is not None else None


CompanyName = Annotated[str | None, Field(max_length=200), AfterValidator(_company)]


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0)
    document_type: DocumentType = DocumentType.ANNUAL_REPORT
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)
    company_name: CompanyName = None
    # SHA-256 of the file (hex). The worker refuses to process bytes that do not match.
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class DocumentUpdate(BaseModel):
    company_name: CompanyName  # groups the user's reports into one company workspace; null clears


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    document_type: DocumentType
    fiscal_year: int | None
    company_name: str | None
    company_id: uuid.UUID | None = None
    mime_type: str
    size_bytes: int
    status: DocumentStatus
    processing_error: str | None
    created_at: datetime
    updated_at: datetime


class SignedUpload(BaseModel):
    url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_at: datetime


class DocumentUpload(BaseModel):
    document: DocumentOut
    upload: SignedUpload


class DocumentList(BaseModel):
    items: list[DocumentOut]


class SignedDownload(BaseModel):
    url: str
    expires_at: datetime


class PageSummary(BaseModel):
    page_number: int  # 1-based physical page, as a PDF viewer numbers it
    label: str | None  # printed page label, when the PDF defines one
    extraction_status: PageExtractionStatus
    char_count: int


class PageList(BaseModel):
    items: list[PageSummary]


class PageOut(BaseModel):
    page_number: int
    label: str | None
    extraction_status: PageExtractionStatus
    text: str
    width: float | None
    height: float | None


class SectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ordinal: int
    title: str | None  # None: no heading detected; never an invented name
    start_page: int
    end_page: int


class SectionList(BaseModel):
    items: list[SectionOut]


# Decimals leave the API as strings: JSON numbers would round-trip through binary floats.
DecimalStr = Annotated[Decimal, PlainSerializer(lambda d: format(d, "f"), return_type=str)]


class EvidenceOut(BaseModel):
    id: uuid.UUID
    page_number: int
    page_label: str | None
    section_title: str | None  # None: the row sits in a section without a detected heading
    chunk_id: uuid.UUID
    kind: str
    content: str  # the verbatim source row, also found in the page text
    header: str | None  # the period header the value sits under
    unit: str | None  # the unit/currency statement the scale came from


class FactOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    metric: str
    metric_name: str
    value: DecimalStr  # full value in currency units, sign preserved
    currency: str | None
    scale: str  # the scale the source printed the value in
    original_text: str
    period_type: PeriodType
    period_label: str
    period_end: date | None
    fiscal_year: int | None
    confidence: DecimalStr
    status: FactStatus
    review_reasons: list[str]
    extraction_method: str
    evidence: EvidenceOut


class FactList(BaseModel):
    items: list[FactOut]
    next_offset: int | None = None  # pass as `offset` for the next page; null on the last page


class CalculationOut(BaseModel):
    id: uuid.UUID
    metric: str  # revenue_growth, net_margin, roa, roe, debt_to_equity, current_ratio
    name: str
    formula_key: str  # e.g. roa_average_assets vs the labeled roa_ending_assets variant
    formula: str
    period_type: PeriodType
    period_label: str
    status: CalculationStatus
    value: DecimalStr | None  # plain ratio at full precision; null unless calculated
    unit: Literal["percent", "times"]  # presentation only; round at display time
    reason_code: str | None  # MISSING_INPUT, DIVISION_BY_ZERO, INCOMPATIBLE_INPUTS
    reason: str | None
    notes: list[str]
    inputs: list[FactOut]  # the source facts; each carries its evidence


class CalculationList(BaseModel):
    items: list[CalculationOut]


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=get_settings().signed_url_ttl_seconds)


def _owned_document(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID, lock: bool = False
) -> Document:
    """The single ownership gate: another user's document is indistinguishable from none."""
    query = select(Document).where(Document.id == document_id, Document.user_id == user_id)
    document = session.scalar(query.with_for_update() if lock else query)
    if document is None:
        if session.scalar(select(Document.id).where(Document.id == document_id)):
            security_event(
                "authorization_denied", user_id=str(user_id), document_id=str(document_id)
            )
        raise ApiError(404, "not_found", "Document not found")
    return document


@router.post("", status_code=201, dependencies=[limit_user("uploads")])
def create_document(
    request: Request,
    body: DocumentCreate,
    user_id: CurrentUserId,
    session: DbSession,
    storage: Storage,
) -> DocumentUpload:
    settings = get_settings()
    if body.content_type != PDF_MIME:
        raise ApiError(415, "unsupported_file_type", "Only PDF files are supported")
    if body.size_bytes > settings.max_upload_bytes:
        security_event("upload_rejected_size", request, declared_bytes=body.size_bytes)
        raise ApiError(413, "file_too_large", "Upload exceeds the maximum allowed size.")
    quotas.check_upload(request, session, user_id, body.size_bytes)  # locks the user row

    document = Document(
        user_id=user_id,
        filename=body.filename,  # display only: never used as a path or storage key
        document_type=body.document_type,
        fiscal_year=body.fiscal_year,
        company_name=body.company_name,
        mime_type=PDF_MIME,
        size_bytes=body.size_bytes,
        sha256=body.sha256,
        # Random, owner-independent key; the bucket is private and only signed URLs reach it.
        storage_key=f"documents/{secrets.token_urlsafe(24)}.pdf",
    )
    session.add(document)
    session.commit()
    return DocumentUpload(
        document=DocumentOut.model_validate(document),
        upload=SignedUpload(
            # Signed for exactly size_bytes of application/pdf: storage rejects anything else.
            url=storage.signed_upload_url(
                document.storage_key, PDF_MIME, body.size_bytes, settings.signed_url_ttl_seconds
            ),
            headers={"Content-Type": PDF_MIME},
            expires_at=_expires_at(),
        ),
    )


def _reject_upload(
    session: Session, storage: ObjectStorage, document: Document, problem: str
) -> ApiError:
    storage.delete(document.storage_key)
    document.status = DocumentStatus.FAILED
    document.processing_error = problem
    document.object_deleted_at = datetime.now(UTC)
    session.commit()
    return ApiError(422, "invalid_upload", problem)


@router.post("/{document_id}/complete", dependencies=[limit_user("complete")])
def complete_upload(
    request: Request,
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
    storage: Storage,
) -> DocumentOut:
    document = _owned_document(session, user_id, document_id, lock=True)
    if document.status != DocumentStatus.UPLOADING:
        return DocumentOut.model_validate(document)  # idempotent: already completed or failed

    stored = storage.stat(document.storage_key)
    if stored is None:
        raise ApiError(409, "upload_not_found", "The file has not been uploaded yet")

    # Never trust the client: check the stored bytes, not the declared size or type.
    if stored.size != document.size_bytes or stored.size > get_settings().max_upload_bytes:
        security_event(
            "upload_rejected_size",
            request,
            document_id=str(document.id),
            declared_bytes=document.size_bytes,
            stored_bytes=stored.size,
        )
        raise _reject_upload(session, storage, document, "Uploaded file size does not match.")
    if (stored.content_type or "").split(";")[0].strip() != PDF_MIME or PDF_MAGIC not in (
        storage.read_prefix(document.storage_key, PDF_HEADER_WINDOW)
    ):
        security_event("upload_rejected_type", request, document_id=str(document.id))
        raise _reject_upload(session, storage, document, "The file is not a valid PDF.")

    quotas.check_processing(request, session, user_id)  # before queueing any work
    document.status = DocumentStatus.UPLOADED
    session.add(ProcessingJob(document_id=document.id))
    session.commit()
    return DocumentOut.model_validate(document)


@router.get("")
def list_documents(
    user_id: CurrentUserId, session: DbSession, limit: Annotated[int, Query(ge=1, le=100)] = 50
) -> DocumentList:
    # ponytail: newest `limit` only; add cursor pagination when users hold >100 documents.
    documents = session.scalars(
        select(Document)
        .where(Document.user_id == user_id)
        .order_by(Document.created_at.desc())
        .limit(limit)
    )
    return DocumentList(items=[DocumentOut.model_validate(d) for d in documents])


@router.get("/{document_id}")
def get_document(document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession) -> DocumentOut:
    return DocumentOut.model_validate(_owned_document(session, user_id, document_id))


@router.patch("/{document_id}")
def update_document(
    document_id: uuid.UUID, body: DocumentUpdate, user_id: CurrentUserId, session: DbSession
) -> DocumentOut:
    document = _owned_document(session, user_id, document_id, lock=True)
    document.company_name = body.company_name
    session.commit()
    return DocumentOut.model_validate(document)


@router.get("/{document_id}/download-url")
def get_download_url(
    document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession, storage: Storage
) -> SignedDownload:
    document = _owned_document(session, user_id, document_id)
    if document.status in (DocumentStatus.UPLOADING, DocumentStatus.FAILED):
        raise ApiError(409, "file_unavailable", "The file is not available")
    return SignedDownload(
        url=storage.signed_download_url(
            document.storage_key, get_settings().signed_url_ttl_seconds
        ),
        expires_at=_expires_at(),
    )


@router.get("/{document_id}/pages")
def list_pages(document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession) -> PageList:
    _owned_document(session, user_id, document_id)
    rows = session.execute(
        select(
            DocumentPage.page_number,
            DocumentPage.page_metadata["label"].astext,
            DocumentPage.extraction_status,
            func.length(DocumentPage.text),
        )
        .where(DocumentPage.document_id == document_id)
        .order_by(DocumentPage.page_number)
    )
    return PageList(
        items=[
            PageSummary(page_number=n, label=label, extraction_status=status, char_count=chars)
            for n, label, status, chars in rows
        ]
    )


@router.get("/{document_id}/pages/{page_number}")
def get_page(
    document_id: uuid.UUID,
    page_number: Annotated[int, Path(ge=1)],
    user_id: CurrentUserId,
    session: DbSession,
) -> PageOut:
    _owned_document(session, user_id, document_id)
    page = session.scalar(
        select(DocumentPage).where(
            DocumentPage.document_id == document_id, DocumentPage.page_number == page_number
        )
    )
    if page is None:
        raise ApiError(404, "not_found", "Page not found")
    meta = page.page_metadata
    return PageOut(
        page_number=page.page_number,
        label=meta.get("label"),
        extraction_status=page.extraction_status,
        text=page.text,
        width=meta.get("width"),
        height=meta.get("height"),
    )


@router.get("/{document_id}/sections")
def list_sections(
    document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> SectionList:
    _owned_document(session, user_id, document_id)
    sections = session.scalars(
        select(DocumentSection)
        .where(DocumentSection.document_id == document_id)
        .order_by(DocumentSection.ordinal)
    )
    return SectionList(items=[SectionOut.model_validate(s) for s in sections])


def _facts(
    session: Session,
    *document_ids: uuid.UUID,
    evidence_id: uuid.UUID | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[FactOut]:
    """The documents' facts with evidence; callers must have checked ownership of every id.

    Only the page label is read from each page (not its text), and paging happens in SQL.
    """
    query = (
        select(
            FinancialFact,
            FinancialMetric,
            Evidence,
            DocumentPage.page_metadata["label"].astext,
            SectionRow.title,
        )
        .join(FinancialMetric, FinancialMetric.id == FinancialFact.metric_id)
        .join(Evidence, Evidence.id == FinancialFact.evidence_id)
        .join(DocumentPage, DocumentPage.id == Evidence.page_id)
        .join(SectionRow, SectionRow.id == Evidence.section_id)
        .where(FinancialFact.document_id.in_(document_ids))
        .order_by(
            FinancialMetric.category,
            FinancialMetric.key,
            FinancialFact.fiscal_year.desc(),
            FinancialFact.id,  # stable order, so pages never skip or repeat a fact
        )
        .offset(offset)
        .limit(limit)
    )
    if evidence_id is not None:
        query = query.where(Evidence.id == evidence_id)
    if limit is None:  # an unpaged load: refuse, before loading, sets too large to hold
        cap = get_settings().financials_max_facts
        total = session.scalar(
            select(func.count())
            .select_from(FinancialFact)
            .where(FinancialFact.document_id.in_(document_ids))
        )
        if (total or 0) > cap:
            security_event("financial_data_limit_exceeded", facts=total, limit=cap)
            raise ApiError(
                413,
                "financial_data_too_large",
                "Too much financial data to load at once. Narrow the scope.",
            )
    rows = session.execute(query)
    return [
        FactOut(
            id=fact.id,
            document_id=fact.document_id,
            metric=metric.key,
            metric_name=metric.name,
            value=fact.value_numeric,
            currency=fact.currency,
            scale=fact.scale,
            original_text=fact.original_text,
            period_type=fact.period_type,
            period_label=fact.period_label,
            period_end=fact.period_end,
            fiscal_year=fact.fiscal_year,
            confidence=fact.confidence,
            status=fact.status,
            review_reasons=fact.review_reasons,
            extraction_method=fact.extraction_method,
            evidence=EvidenceOut(
                id=evidence.id,
                page_number=evidence.page_number,
                page_label=page_label,
                section_title=section_title,
                chunk_id=evidence.chunk_id,
                kind=evidence.evidence_type.value,
                content=evidence.content,
                header=evidence.locator.get("header"),
                unit=evidence.locator.get("unit"),
            ),
        )
        for fact, metric, evidence, page_label, section_title in rows
    ]


_PAGE = get_settings()


@router.get("/{document_id}/metrics")
def list_facts(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=_PAGE.page_max_limit)] = _PAGE.page_default_limit,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FactList:
    """Extracted financial facts with their evidence, one page at a time (PAGE_MAX_LIMIT)."""
    _owned_document(session, user_id, document_id)
    items = _facts(session, document_id, limit=limit + 1, offset=offset)
    more = len(items) > limit
    return FactList(items=items[:limit], next_offset=offset + limit if more else None)


@router.get("/{document_id}/calculations")
def list_calculations(
    document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> CalculationList:
    """Deterministic ratios, each with its formula and the source facts (and their evidence)."""
    _owned_document(session, user_id, document_id)
    facts = {f.id: f for f in _facts(session, document_id)}
    inputs: dict[uuid.UUID, list[uuid.UUID]] = {}
    for calculation_id, fact_id in session.execute(
        select(CalculationInput.calculation_id, CalculationInput.financial_fact_id).where(
            CalculationInput.document_id == document_id
        )
    ):
        inputs.setdefault(calculation_id, []).append(fact_id)
    calculations = session.scalars(
        select(Calculation).where(Calculation.document_id == document_id)
    )
    items = []
    for c in calculations:
        _, name, formula, _ = FORMULAS[c.formula_key]
        used = sorted(
            (facts[i] for i in inputs.get(c.id, [])),
            key=lambda f: (INPUT_ORDER.index(f.metric), f.period_label),
        )
        items.append(
            CalculationOut(
                id=c.id,
                metric=c.metric_key,
                name=name,
                formula_key=c.formula_key,
                formula=formula,
                period_type=c.period_type,
                period_label=c.period_label,
                status=c.status,
                value=c.result_numeric,
                unit=c.unit,
                reason_code=c.reason_code,
                reason=c.reason,
                notes=c.notes,
                inputs=used,
            )
        )
    items.sort(key=lambda i: (METRIC_ORDER.index(i.metric), i.period_label))
    return CalculationList(items=items)
