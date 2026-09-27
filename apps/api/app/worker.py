"""Document-processing worker: polls processing_jobs (docs/DEPLOYMENT.md §5, option A).

Run: `python -m app.worker`. Deployed as its own Railway/Render service from this codebase.

Lifecycle (PRD §22): UPLOADED → PROCESSING → READY, or FAILED. Transient errors put the job
back to QUEUED (with backoff) up to MAX_ATTEMPTS. A job whose worker died is reclaimed once its
lease expires, so a document never stays in PROCESSING indefinitely.
"""

import logging
import os
import signal
import tempfile
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from app.analytics import FactInput, calculate
from app.config import get_settings
from app.db import SessionLocal
from app.extraction import extract_facts
from app.logs import configure_logging
from app.models import (
    Calculation,
    CalculationInput,
    CalculationStatus,
    Document,
    DocumentChunk,
    DocumentPage,
    DocumentSection,
    DocumentStatus,
    Evidence,
    EvidenceType,
    FactStatus,
    FinancialFact,
    FinancialMetric,
    JobStatus,
    PageExtractionStatus,
    PeriodType,
    ProcessingJob,
)
from app.processing import ParsedPage, ProcessingError, chunk_pages, detect_sections, parse_pdf
from app.storage import ObjectStorage, get_storage

log = logging.getLogger("prospect.worker")

MAX_ATTEMPTS = 3
LEASE = timedelta(minutes=15)  # a RUNNING job older than this is presumed dead and reclaimed
RETRY_BACKOFF = timedelta(seconds=30)  # multiplied by attempts so far
POLL_SECONDS = 2.0
INTERNAL_ERROR = "Processing failed due to an internal error."


def claim_job(session: Session) -> ProcessingJob | None:
    """Atomically take the oldest runnable job. SKIP LOCKED lets several workers run safely."""
    now = datetime.now(UTC)
    runnable = or_(
        and_(
            ProcessingJob.status == JobStatus.QUEUED,
            or_(
                ProcessingJob.attempts == 0,
                ProcessingJob.updated_at < now - RETRY_BACKOFF * ProcessingJob.attempts,
            ),
        ),
        and_(ProcessingJob.status == JobStatus.RUNNING, ProcessingJob.locked_at < now - LEASE),
    )
    job = session.scalar(
        select(ProcessingJob)
        .where(runnable)
        .order_by(ProcessingJob.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.locked_at = now
    job.attempts += 1
    document = session.get_one(Document, job.document_id)
    document.status = DocumentStatus.PROCESSING
    document.processing_error = None
    session.commit()
    return job


def process_next(storage: ObjectStorage) -> bool:
    """Process one job. Returns False when there was nothing to do."""
    with SessionLocal() as session:
        job = claim_job(session)
        if job is None:
            return False
        job_id, document_id, attempts = job.id, job.document_id, job.attempts
        storage_key = session.get_one(Document, document_id).storage_key

    fields = {"job_id": str(job_id), "document_id": str(document_id), "attempt": attempts}
    if attempts > MAX_ATTEMPTS:  # reclaimed after crashing its worker too many times
        _fail(job_id, document_id, f"Processing did not complete after {MAX_ATTEMPTS} attempts.")
        log.error("job abandoned", extra={"fields": fields})
        return True

    started = time.perf_counter()
    log.info("processing started", extra={"fields": fields})
    try:
        # ignore_cleanup_errors: on Windows a failed open can briefly hold the file.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path = Path(tmp) / "document.pdf"
            storage.download_file(storage_key, path)
            pages = parse_pdf(path)
        _store(job_id, document_id, pages)
    except ProcessingError as e:
        _fail(job_id, document_id, str(e))
        log.warning("processing rejected document", extra={"fields": fields | {"reason": str(e)}})
    except Exception:
        log.exception("processing error", extra={"fields": fields})
        if attempts < MAX_ATTEMPTS:
            _requeue(job_id, document_id)
        else:
            _fail(job_id, document_id, f"{INTERNAL_ERROR} Tried {MAX_ATTEMPTS} times.")
    else:
        duration = round(time.perf_counter() - started, 2)
        log.info(
            "processing finished",
            extra={"fields": fields | {"pages": len(pages), "duration_s": duration}},
        )
    return True


def _store(job_id: uuid.UUID, document_id: uuid.UUID, pages: list[ParsedPage]) -> None:
    """Replace the document's pages/sections/chunks/facts and mark it READY, in one transaction.

    Delete-then-insert makes a retried job idempotent: no duplicates, no partial results.
    """
    sections, assignment = detect_sections(pages)
    chunks = chunk_pages(pages, assignment)
    facts, rejections = extract_facts(pages, sections, assignment, chunks)
    page_ids = {p.number: uuid.uuid4() for p in pages}
    section_ids = {s.ordinal: uuid.uuid4() for s in sections}
    chunk_ids = {(c.page_number, c.chunk_index): uuid.uuid4() for c in chunks}
    blocks = {(p.number, b.index): b for p in pages for b in p.blocks}

    with SessionLocal() as session, session.begin():
        for model in (
            Calculation,
            FinancialFact,
            Evidence,
            DocumentChunk,
            DocumentSection,
            DocumentPage,
        ):
            session.execute(delete(model).where(model.document_id == document_id))
        session.add_all(
            DocumentPage(
                id=page_ids[p.number],
                document_id=document_id,
                page_number=p.number,
                text=p.text,
                extraction_status=PageExtractionStatus(p.extraction_status),
                page_metadata=p.metadata,
                blocks=[b.to_json() for b in p.blocks],
            )
            for p in pages
        )
        session.add_all(
            DocumentSection(
                id=section_ids[s.ordinal],
                document_id=document_id,
                ordinal=s.ordinal,
                title=s.title,
                start_page=s.start_page,
                end_page=s.end_page,
            )
            for s in sections
        )
        session.flush()  # chunks reference pages and sections
        session.add_all(
            DocumentChunk(
                id=chunk_ids[(c.page_number, c.chunk_index)],
                document_id=document_id,
                page_id=page_ids[c.page_number],
                page_number=c.page_number,
                section_id=section_ids[c.section_ordinal],
                chunk_index=c.chunk_index,
                block_start=c.block_start,
                block_end=c.block_end,
                content=c.content,
            )
            for c in chunks
        )
        session.flush()  # evidence references chunks

        metric_ids = dict(session.execute(select(FinancialMetric.key, FinancialMetric.id)).all())
        accepted: list[FactInput] = []
        for fact in facts:
            c = fact.candidate
            evidence = Evidence(
                id=uuid.uuid4(),
                document_id=document_id,
                page_id=page_ids[c.page_number],
                page_number=c.page_number,
                section_id=section_ids[fact.section_ordinal],
                chunk_id=chunk_ids[(c.page_number, fact.chunk_index)],
                evidence_type=EvidenceType(c.source_kind),
                content=c.source_text,
                bbox_json=list(blocks[(c.page_number, c.block_index)].bbox),
                locator={
                    "block_index": c.block_index,
                    "row_index": c.row_index,
                    "column_index": c.column_index,
                    "header": c.header_text,
                    "unit": c.unit_text,
                },
            )
            session.add(evidence)
            session.flush()  # the fact references its evidence
            row = FinancialFact(
                id=uuid.uuid4(),
                document_id=document_id,
                metric_id=metric_ids[c.metric],
                evidence_id=evidence.id,
                value_numeric=c.amount.value,
                currency=c.amount.currency,
                scale=c.amount.scale,
                original_text=c.amount.original_text[:100],
                original_unit=c.unit_text,
                period_type=PeriodType(c.period.type),
                period_end=c.period.end,
                period_label=c.period.label,
                fiscal_year=c.period.fiscal_year,
                confidence=fact.confidence,
                extraction_method="parser",
                status=FactStatus(fact.status),
                review_reasons=fact.review_reasons,
            )
            session.add(row)
            if row.status == FactStatus.ACCEPTED and row.currency:
                accepted.append(
                    FactInput(
                        row.id,
                        c.metric,
                        row.value_numeric,
                        row.currency,
                        c.period.type,
                        c.period.label,
                        c.period.end,
                        c.period.fiscal_year,
                    )
                )
        session.flush()  # calculation inputs reference the facts
        calculations = calculate(accepted)
        for result in calculations:
            calculation = Calculation(
                id=uuid.uuid4(),
                document_id=document_id,
                metric_key=result.metric,
                formula_key=result.formula_key,
                period_type=PeriodType(result.period_type),
                period_label=result.period_label,
                status=CalculationStatus(result.status),
                result_numeric=result.value,
                unit=result.unit,
                reason_code=result.reason_code,
                reason=result.reason,
                notes=list(result.notes),
            )
            session.add(calculation)
            session.flush()
            session.add_all(
                CalculationInput(
                    calculation_id=calculation.id, financial_fact_id=i, document_id=document_id
                )
                for i in result.input_ids
            )
        log.info(
            "financial extraction",
            extra={
                "fields": {
                    "document_id": str(document_id),
                    "accepted": sum(f.status == "accepted" for f in facts),
                    "needs_review": sum(f.status == "needs_review" for f in facts),
                    "rejected": len(rejections),
                    "calculated": sum(r.status == "calculated" for r in calculations),
                    "not_possible": sum(r.status == "not_possible" for r in calculations),
                    "rejections": [f"p{r.page_number}: {r.reason}" for r in rejections[:20]],
                }
            },
        )
        document = session.get_one(Document, document_id)
        document.status = DocumentStatus.READY
        document.processing_error = None
        job = session.get_one(ProcessingJob, job_id)
        job.status = JobStatus.SUCCEEDED
        job.last_error = None
        job.locked_at = None


def _fail(job_id: uuid.UUID, document_id: uuid.UUID, reason: str) -> None:
    with SessionLocal() as session, session.begin():
        job = session.get_one(ProcessingJob, job_id)
        job.status = JobStatus.FAILED
        job.last_error = reason
        job.locked_at = None
        document = session.get_one(Document, document_id)
        document.status = DocumentStatus.FAILED
        document.processing_error = reason  # user-safe: ProcessingError text or a generic message


def _requeue(job_id: uuid.UUID, document_id: uuid.UUID) -> None:
    with SessionLocal() as session, session.begin():
        job = session.get_one(ProcessingJob, job_id)
        job.status = JobStatus.QUEUED
        job.last_error = INTERNAL_ERROR
        job.locked_at = None
        session.get_one(Document, document_id).status = DocumentStatus.QUEUED


class _Health(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, *args) -> None:  # keep platform health probes out of the logs
        pass


def main() -> None:
    configure_logging(get_settings().log_level)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    # Railway/Render inject PORT when a service should answer health checks.
    if port := os.getenv("PORT"):
        server = ThreadingHTTPServer(("0.0.0.0", int(port)), _Health)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    storage = get_storage()
    log.info("worker started")
    while not stop.is_set():
        try:
            worked = process_next(storage)
        except Exception:  # e.g. database unreachable: keep the worker alive and retry
            log.exception("worker loop error")
            worked = False
        if not worked:
            stop.wait(POLL_SECONDS)
    log.info("worker stopped")


if __name__ == "__main__":
    main()
