"""Per-user resource quotas (plus one global queue cap), checked before expensive work.

Each check first locks the user's row (SELECT ... FOR UPDATE) and runs inside the caller's
transaction, so concurrent requests from one user are serialized: count, then insert, then commit
releases the lock. Two parallel uploads cannot both see "one slot left".
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.errors import ApiError
from app.logs import security_event
from app.models import Document, DocumentStatus, JobStatus, ProcessingJob, User


def lock_user(session: Session, user_id: uuid.UUID) -> None:
    # FOR NO KEY UPDATE: serializes quota checks for this user, yet lets rows that reference
    # the user (audit events, written on their own connection) be inserted meanwhile.
    session.execute(select(User.id).where(User.id == user_id).with_for_update(key_share=True))


def _exceeded(request: Request, quota: str, status: int, message: str) -> ApiError:
    security_event("quota_exceeded", request, quota=quota)
    return ApiError(status, "quota_exceeded", message)


def check_upload(request: Request, session: Session, user_id: uuid.UUID, size: int) -> None:
    """Document count and stored bytes, including uploads still in progress."""
    settings = get_settings()
    lock_user(session, user_id)
    documents, stored = session.execute(
        select(func.count(), func.coalesce(func.sum(Document.size_bytes), 0)).where(
            Document.user_id == user_id,
            Document.status != DocumentStatus.FAILED,
            Document.object_deleted_at.is_(None),
        )
    ).one()
    if documents >= settings.quota_max_documents:
        raise _exceeded(request, "documents", 409, "Document limit reached.")
    if stored + size > settings.quota_max_storage_bytes:
        raise _exceeded(request, "storage", 409, "Storage limit reached.")


def check_count(
    request: Request, session: Session, user_id: uuid.UUID, model: Any, limit: int, quota: str
) -> None:
    """How many rows of `model` (companies, scenarios) one user may keep. Without it a single
    anonymous session could grow the database without bound."""
    lock_user(session, user_id)
    count = session.scalar(select(func.count()).select_from(model).where(model.user_id == user_id))
    if (count or 0) >= limit:
        raise _exceeded(request, quota, 409, f"Limit of {limit} reached.")


def check_processing(request: Request, session: Session, user_id: uuid.UUID) -> None:
    """Concurrent and daily processing jobs."""
    settings = get_settings()
    lock_user(session, user_id)
    mine = select(func.count()).select_from(ProcessingJob).join(Document)
    mine = mine.where(Document.user_id == user_id)
    active = session.scalar(
        mine.where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
    )
    if (active or 0) >= settings.quota_max_active_jobs:
        raise _exceeded(
            request, "active_jobs", 429, "Too many documents are processing. Try again later."
        )
    since = datetime.now(UTC) - timedelta(days=1)
    if (session.scalar(mine.where(ProcessingJob.created_at > since)) or 0) >= (
        settings.quota_max_daily_jobs
    ):
        raise _exceeded(request, "daily_jobs", 429, "Daily processing limit reached.")
    # ponytail: global cap read without a global lock, so concurrent completes can overshoot it
    # by a few jobs; it bounds a flood from many new sessions, not a precise budget.
    queued = session.scalar(
        select(func.count())
        .select_from(ProcessingJob)
        .where(ProcessingJob.status.in_([JobStatus.QUEUED, JobStatus.RUNNING]))
    )
    if (queued or 0) >= settings.quota_max_queued_jobs:
        raise _exceeded(request, "queued_jobs", 503, "Processing is busy. Try again later.")
