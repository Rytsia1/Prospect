"""Document upload + metadata endpoints (docs/API_SPEC.yaml, docs/DEPLOYMENT.md §4).

Upload flow: POST /documents (signed PUT URL) → browser PUTs the PDF to private storage →
POST /documents/{id}/complete verifies the stored bytes server-side and queues processing.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUserId
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import Document, DocumentStatus, DocumentType, ProcessingJob
from app.storage import ObjectStorage, get_storage

PDF_MIME = "application/pdf"
PDF_MAGIC = b"%PDF-"
PDF_HEADER_WINDOW = 1024  # PDF readers accept the header anywhere in the first 1 KiB
SIGNED_URL_TTL_SECONDS = 900

router = APIRouter(prefix="/documents", tags=["documents"])
DbSession = Annotated[Session, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]


class DocumentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str
    size_bytes: int = Field(gt=0)
    document_type: DocumentType = DocumentType.ANNUAL_REPORT
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    document_type: DocumentType
    fiscal_year: int | None
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


def _expires_at() -> datetime:
    return datetime.now(UTC) + timedelta(seconds=SIGNED_URL_TTL_SECONDS)


def _owned_document(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID, lock: bool = False
) -> Document:
    """The single ownership gate: another user's document is indistinguishable from none."""
    query = select(Document).where(Document.id == document_id, Document.user_id == user_id)
    document = session.scalar(query.with_for_update() if lock else query)
    if document is None:
        raise ApiError(404, "not_found", "Document not found")
    return document


@router.post("", status_code=201)
def create_document(
    body: DocumentCreate, user_id: CurrentUserId, session: DbSession, storage: Storage
) -> DocumentUpload:
    if body.content_type != PDF_MIME:
        raise ApiError(415, "unsupported_file_type", "Only PDF files are supported")
    limit = get_settings().max_upload_bytes
    if body.size_bytes > limit:
        raise ApiError(413, "file_too_large", f"File exceeds the {limit // (1024 * 1024)} MB limit")

    document = Document(
        user_id=user_id,
        filename=body.filename,
        document_type=body.document_type,
        fiscal_year=body.fiscal_year,
        mime_type=PDF_MIME,
        size_bytes=body.size_bytes,
        # Random, owner-independent key; the bucket is private and only signed URLs reach it.
        storage_key=f"documents/{secrets.token_urlsafe(24)}.pdf",
    )
    session.add(document)
    session.commit()
    return DocumentUpload(
        document=DocumentOut.model_validate(document),
        upload=SignedUpload(
            url=storage.signed_url(document.storage_key, "put", SIGNED_URL_TTL_SECONDS),
            headers={"Content-Type": PDF_MIME},
            expires_at=_expires_at(),
        ),
    )


@router.post("/{document_id}/complete")
def complete_upload(
    document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession, storage: Storage
) -> DocumentOut:
    document = _owned_document(session, user_id, document_id, lock=True)
    if document.status != DocumentStatus.UPLOADING:
        return DocumentOut.model_validate(document)  # idempotent: already completed or failed

    size = storage.size(document.storage_key)
    if size is None:
        raise ApiError(409, "upload_not_found", "The file has not been uploaded yet")

    # Never trust the client: check the stored bytes, not the declared type.
    problem = None
    if size != document.size_bytes:
        problem = "Uploaded file size does not match the selected file."
    elif PDF_MAGIC not in storage.read_prefix(document.storage_key, PDF_HEADER_WINDOW):
        problem = "The file is not a valid PDF."
    if problem:
        storage.delete(document.storage_key)
        document.status = DocumentStatus.FAILED
        document.processing_error = problem
        session.commit()
        raise ApiError(422, "invalid_upload", problem)

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


@router.get("/{document_id}/download-url")
def get_download_url(
    document_id: uuid.UUID, user_id: CurrentUserId, session: DbSession, storage: Storage
) -> SignedDownload:
    document = _owned_document(session, user_id, document_id)
    if document.status in (DocumentStatus.UPLOADING, DocumentStatus.FAILED):
        raise ApiError(409, "file_unavailable", "The file is not available")
    return SignedDownload(
        url=storage.signed_url(document.storage_key, "get", SIGNED_URL_TTL_SECONDS),
        expires_at=_expires_at(),
    )
