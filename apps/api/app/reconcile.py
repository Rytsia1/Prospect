"""Storage ↔ database reconciliation (docs/SECURITY.md §9). Conservative by design.

Finds, in one pass:
- orphan objects: under Prospect's own prefixes (uploads/, documents/) with no document row.
  Deleted (with delete=True) only when also older than RECONCILE_ORPHAN_GRACE_HOURS and still
  unknown when re-checked right before the delete. Keys outside those prefixes are never listed;
- missing objects: documents the database says are stored (not UPLOADING, not FAILED, not
  deleted) whose object is gone. Reported only: the worker fails such a document when it next
  reads it, and a person should look at why;
- stuck jobs: RUNNING past the lease (the worker reclaims these; counted for visibility).

Run daily by the worker (with delete) or by hand: `python -m app.reconcile [--delete]`.
"""

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.logs import security_event
from app.models import Document, DocumentStatus, JobStatus, ProcessingJob
from app.storage import DOCUMENT_PREFIX, UPLOAD_PREFIX, ObjectStorage, get_storage

MISSING_CHECK_LIMIT = 1000  # HEAD requests per run for the missing-object check


@dataclass
class Report:
    orphan_objects: list[str] = field(default_factory=list)  # eligible: unknown and old enough
    recent_unknown_objects: int = 0  # unknown but inside the grace window: left alone
    deleted_objects: list[str] = field(default_factory=list)
    missing_objects: list[uuid.UUID] = field(default_factory=list)
    stuck_jobs: int = 0


def reconcile(storage: ObjectStorage, delete: bool = False, now: datetime | None = None) -> Report:
    settings = get_settings()
    now = now or datetime.now(UTC)
    report = Report()
    with SessionLocal() as session:
        # ponytail: every key in memory; page through documents by key range past ~10^6 rows.
        known = set(session.scalars(select(Document.storage_key)))
        old = now - timedelta(hours=settings.reconcile_orphan_grace_hours)
        for prefix in (UPLOAD_PREFIX, DOCUMENT_PREFIX):
            for key, modified in storage.list_objects(prefix):
                if key in known:
                    continue
                if modified >= old:
                    report.recent_unknown_objects += 1
                    continue
                report.orphan_objects.append(key)
        for key in report.orphan_objects:
            if not delete:
                continue
            # Re-check: a row may have been created since the set was read.
            if session.scalar(select(Document.id).where(Document.storage_key == key)) is None:
                storage.delete(key)
                report.deleted_objects.append(key)

        stored = session.execute(
            select(Document.id, Document.storage_key)
            .where(
                Document.status.not_in([DocumentStatus.UPLOADING, DocumentStatus.FAILED]),
                Document.object_deleted_at.is_(None),
            )
            .order_by(Document.created_at.desc())
            .limit(MISSING_CHECK_LIMIT)
        ).all()
        for document_id, key in stored:
            if storage.stat(key) is None:
                report.missing_objects.append(document_id)
                security_event("object_missing", document_id=str(document_id))

        lease = timedelta(seconds=settings.processing_lease_seconds)
        report.stuck_jobs = (
            session.scalar(
                select(func.count())
                .select_from(ProcessingJob)
                .where(
                    ProcessingJob.status == JobStatus.RUNNING,
                    ProcessingJob.locked_at < now - lease,
                )
            )
            or 0
        )
    if report.orphan_objects or report.missing_objects or report.stuck_jobs:
        security_event(
            "reconciliation",
            orphan_objects=len(report.orphan_objects),
            deleted_objects=len(report.deleted_objects),
            missing_objects=len(report.missing_objects),
            stuck_jobs=report.stuck_jobs,
        )
    return report


if __name__ == "__main__":
    if sys.argv[1:] not in ([], ["--delete"]):
        sys.exit("usage: python -m app.reconcile [--delete]")
    result = reconcile(get_storage(), delete=sys.argv[1:] == ["--delete"])
    print(f"orphan objects (older than grace): {len(result.orphan_objects)}")
    print(f"deleted: {len(result.deleted_objects)}")
    print(f"unknown but recent (kept): {result.recent_unknown_objects}")
    print(f"documents whose object is missing: {[str(i) for i in result.missing_objects]}")
    print(f"stuck jobs: {result.stuck_jobs}")
