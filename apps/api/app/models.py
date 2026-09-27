"""Relational schema (docs/DATA_MODEL.md). Keep in sync with migrations/versions."""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class DocumentType(enum.StrEnum):
    ANNUAL_REPORT = "annual_report"
    FINANCIAL_STATEMENT = "financial_statement"
    PROSPECTUS = "prospectus"


class DocumentStatus(enum.StrEnum):
    # Mirrors Document.status in docs/API_SPEC.yaml.
    UPLOADING = "UPLOADING"  # signed URL issued, bytes not yet verified
    UPLOADED = "UPLOADED"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    EXTRACTING = "EXTRACTING"
    INDEXING = "INDEXING"
    READY = "READY"
    FAILED = "FAILED"


class PageExtractionStatus(enum.StrEnum):
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"


class FactStatus(enum.StrEnum):
    ACCEPTED = "accepted"  # authoritative: may be shown as a FACT and used in calculations
    NEEDS_REVIEW = "needs_review"  # kept for audit; never presented as a fact
    CORRECTED = "corrected"  # authoritative: manually corrected by a reviewer
    REJECTED = "rejected"  # rejected by a reviewer; never presented as a fact


class PeriodType(enum.StrEnum):
    ANNUAL = "annual"
    QUARTER = "quarter"
    INTERIM = "interim"  # other durations, e.g. nine months
    INSTANT = "instant"  # balance-sheet date


class EvidenceType(enum.StrEnum):
    TABLE_ROW = "table_row"
    TEXT_LINE = "text_line"


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _enum(cls: type[enum.Enum], name: str) -> Enum:
    return Enum(cls, name=name, values_callable=lambda e: [m.value for m in e])


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _updated_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # NULL for anonymous single-user-mode identities (app/auth.py).
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime] = _created_at()


class UserSession(Base):
    """A signed bearer token's server-side record: expiry and revocation (app/auth.py)."""

    __tablename__ = "sessions"
    __table_args__ = (Index("ix_sessions_user_id", "user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created_at()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateLimitCounter(Base):
    """Fixed-window request counters shared by every API instance (app/ratelimit.py)."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)  # bucket:subject:window
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (
        Index("ix_companies_user_id_created_at", "user_id", "created_at"),
        UniqueConstraint("user_id", "name", name="uq_companies_user_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    ticker: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(50))
    currency: Mapped[str | None] = mapped_column(String(3))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_user_id_created_at", "user_id", "created_at"),
        CheckConstraint("fiscal_year BETWEEN 1900 AND 2200", name="ck_documents_fiscal_year"),
        CheckConstraint("size_bytes > 0", name="ck_documents_size_bytes"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    document_type: Mapped[DocumentType] = mapped_column(_enum(DocumentType, "document_type"))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    # User-entered; groups a user's reports into one company workspace (whitespace-collapsed,
    # compared case-insensitively). NULL: the document stands alone.
    company_name: Mapped[str | None] = mapped_column(String(200))
    mime_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # Private object key; never a public URL (AGENTS rule 14).
    storage_key: Mapped[str] = mapped_column(String(1024), unique=True)
    status: Mapped[DocumentStatus] = mapped_column(
        _enum(DocumentStatus, "document_status"), default=DocumentStatus.UPLOADING
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    # Client-declared SHA-256 (hex) of the file; the worker verifies the stored bytes against it.
    sha256: Mapped[str | None] = mapped_column(String(64))
    # Set once the stored object is deleted (failed or abandoned upload); frees storage quota.
    object_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        UniqueConstraint("document_id", "page_number"),
        # Target of the chunk composite FK: a chunk's document/page number must match its page.
        UniqueConstraint("id", "document_id", "page_number", name="uq_document_pages_identity"),
        CheckConstraint("page_number >= 1", name="ck_document_pages_page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    page_number: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, default="")
    extraction_status: Mapped[PageExtractionStatus] = mapped_column(
        _enum(PageExtractionStatus, "page_extraction_status")
    )
    # label (printed page label), width/height (points), rotation, has_images, table_count.
    page_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    # Ordered text/table blocks with bboxes (app/processing.py Block.to_json) for evidence.
    blocks: Mapped[list] = mapped_column(JSONB, server_default="[]")


class DocumentSection(Base):
    __tablename__ = "document_sections"
    __table_args__ = (
        Index("ix_document_sections_document_id_start_page", "document_id", "start_page"),
        UniqueConstraint("document_id", "ordinal", name="uq_document_sections_ordinal"),
        UniqueConstraint("id", "document_id", name="uq_document_sections_identity"),
        CheckConstraint("ordinal >= 0", name="ck_document_sections_ordinal"),
        CheckConstraint(
            "start_page >= 1 AND end_page >= start_page", name="ck_document_sections_page_range"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    ordinal: Mapped[int] = mapped_column(Integer)  # document order
    # Verbatim heading text. NULL = generic section: no heading was detected with confidence.
    title: Mapped[str | None] = mapped_column(String(500))
    start_page: Mapped[int] = mapped_column(Integer)
    end_page: Mapped[int] = mapped_column(Integer)


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("page_id", "chunk_index"),
        UniqueConstraint("id", "page_id", name="uq_document_chunks_page_identity"),
        CheckConstraint("chunk_index >= 0", name="ck_document_chunks_chunk_index"),
        CheckConstraint(
            "block_start >= 0 AND block_end >= block_start", name="ck_document_chunks_blocks"
        ),
        # Document → page → section → chunk, enforced by the database, not just by the worker.
        ForeignKeyConstraint(
            ["page_id", "document_id", "page_number"],
            ["document_pages.id", "document_pages.document_id", "document_pages.page_number"],
            name="fk_document_chunks_page",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["section_id", "document_id"],
            ["document_sections.id", "document_sections.document_id"],
            name="fk_document_chunks_section",
            ondelete="CASCADE",
        ),
        Index("ix_document_chunks_document_order", "document_id", "page_number", "chunk_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_document_chunks_document")
    )
    page_id: Mapped[uuid.UUID] = mapped_column()
    page_number: Mapped[int] = mapped_column(Integer)
    section_id: Mapped[uuid.UUID] = mapped_column()
    chunk_index: Mapped[int] = mapped_column(Integer)  # order within the page
    # Inclusive range into document_pages.blocks: the chunk's source regions on the page.
    block_start: Mapped[int] = mapped_column(Integer)
    block_end: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    # ponytail: embedding VECTOR(n) + index added in Phase 5 once the embedding model fixes n.


class ProcessingJob(Base):
    """Database-backed job queue polled by the worker (docs/DEPLOYMENT.md §5, option A)."""

    __tablename__ = "processing_jobs"
    __table_args__ = (
        Index("ix_processing_jobs_status_created_at", "status", "created_at"),
        Index("ix_processing_jobs_document_id", "document_id"),
        CheckConstraint("attempts >= 0", name="ck_processing_jobs_attempts"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    status: Mapped[JobStatus] = mapped_column(
        _enum(JobStatus, "job_status"), default=JobStatus.QUEUED
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # retry backoff
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class FinancialMetric(Base):
    """Metric definitions (seeded by migration 0004)."""

    __tablename__ = "financial_metrics"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    category: Mapped[str] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)


class Evidence(Base):
    """The exact source of a fact: a row on a page, inside a section and a chunk."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_document_id_page_id", "document_id", "page_id"),
        UniqueConstraint("id", "document_id", name="uq_evidence_identity"),
        ForeignKeyConstraint(
            ["page_id", "document_id", "page_number"],
            ["document_pages.id", "document_pages.document_id", "document_pages.page_number"],
            name="fk_evidence_page",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["section_id", "document_id"],
            ["document_sections.id", "document_sections.document_id"],
            name="fk_evidence_section",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["chunk_id", "page_id"],
            ["document_chunks.id", "document_chunks.page_id"],
            name="fk_evidence_chunk",
            ondelete="CASCADE",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_evidence_document")
    )
    page_id: Mapped[uuid.UUID] = mapped_column()
    page_number: Mapped[int] = mapped_column(Integer)
    section_id: Mapped[uuid.UUID] = mapped_column()
    chunk_id: Mapped[uuid.UUID] = mapped_column()
    evidence_type: Mapped[EvidenceType] = mapped_column(_enum(EvidenceType, "evidence_type"))
    content: Mapped[str] = mapped_column(Text)  # verbatim source row; a substring of the page text
    bbox_json: Mapped[list | None] = mapped_column(JSONB)  # [x0, y0, x1, y1] of the source block
    # block_index, row_index, column_index, header (period header text), unit (unit statement)
    locator: Mapped[dict] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()


class FinancialFact(Base):
    __tablename__ = "financial_facts"
    __table_args__ = (
        Index(
            "ix_financial_facts_document_metric_period", "document_id", "metric_id", "period_end"
        ),
        # One authoritative value per metric and period in a document.
        Index(
            "uq_financial_facts_accepted",
            "document_id",
            "metric_id",
            "period_type",
            "period_label",
            unique=True,
            postgresql_where="status IN ('accepted', 'corrected')",
            sqlite_where=sql_text("status IN ('accepted', 'corrected')"),
        ),
        ForeignKeyConstraint(
            ["evidence_id", "document_id"],
            ["evidence.id", "evidence.document_id"],
            name="fk_financial_facts_evidence",
            ondelete="CASCADE",
        ),
        UniqueConstraint("id", "document_id", name="uq_financial_facts_identity"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_financial_facts_confidence"),
        # Currency is never guessed: an unstated currency cannot be authoritative.
        CheckConstraint(
            "status NOT IN ('accepted', 'corrected') OR currency IS NOT NULL",
            name="ck_financial_facts_currency",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_financial_facts_document")
    )
    metric_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_metrics.id"))
    evidence_id: Mapped[uuid.UUID] = mapped_column()  # required: no fact without evidence
    # Full value in currency units (scale applied), sign preserved. NUMERIC, never float.
    value_numeric: Mapped[Decimal] = mapped_column(Numeric)
    currency: Mapped[str | None] = mapped_column(String(3))
    scale: Mapped[str] = mapped_column(String(16))  # presentation scale in the source
    original_text: Mapped[str] = mapped_column(String(100))  # the cell as printed, e.g. "(1,250)"
    original_unit: Mapped[str | None] = mapped_column(
        Text
    )  # e.g. "(expressed in millions of Rupiah)"
    period_type: Mapped[PeriodType] = mapped_column(_enum(PeriodType, "period_type"))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)  # NULL when only the year is stated
    period_label: Mapped[str] = mapped_column(String(40))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    extraction_method: Mapped[str] = mapped_column(String(20))
    status: Mapped[FactStatus] = mapped_column(_enum(FactStatus, "fact_status"))
    review_reasons: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = _created_at()


class CalculationStatus(enum.StrEnum):
    CALCULATED = "calculated"
    NOT_POSSIBLE = "not_possible"  # missing input, zero denominator, or incompatible inputs


class Calculation(Base):
    """A deterministic ratio computed from facts (app/analytics.py); never from an LLM."""

    __tablename__ = "calculations"
    __table_args__ = (
        UniqueConstraint("id", "document_id", name="uq_calculations_identity"),
        UniqueConstraint(
            "document_id",
            "metric_key",
            "period_type",
            "period_label",
            name="uq_calculations_period",
        ),
        # A result exists exactly when the calculation was possible; never a stand-in zero.
        CheckConstraint(
            "(status = 'calculated') = (result_numeric IS NOT NULL)",
            name="ck_calculations_result",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE", name="fk_calculations_document")
    )
    metric_key: Mapped[str] = mapped_column(String(64))  # e.g. roa
    formula_key: Mapped[str] = mapped_column(String(64))  # e.g. roa_average_assets
    period_type: Mapped[PeriodType] = mapped_column(_enum(PeriodType, "period_type"))
    period_label: Mapped[str] = mapped_column(String(40))
    status: Mapped[CalculationStatus] = mapped_column(
        _enum(CalculationStatus, "calculation_status")
    )
    result_numeric: Mapped[Decimal | None] = mapped_column(Numeric)  # plain ratio, full precision
    unit: Mapped[str] = mapped_column(String(16))  # presentation: percent | times
    reason_code: Mapped[str | None] = mapped_column(String(32))  # MISSING_INPUT, ...
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = _created_at()


class CalculationInput(Base):
    """The facts a calculation used; both must belong to the same document."""

    __tablename__ = "calculation_inputs"
    __table_args__ = (
        Index("ix_calculation_inputs_fact", "financial_fact_id", "document_id"),
        ForeignKeyConstraint(
            ["calculation_id", "document_id"],
            ["calculations.id", "calculations.document_id"],
            name="fk_calculation_inputs_calculation",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["financial_fact_id", "document_id"],
            ["financial_facts.id", "financial_facts.document_id"],
            name="fk_calculation_inputs_fact",
            ondelete="CASCADE",
        ),
    )

    calculation_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    financial_fact_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    document_id: Mapped[uuid.UUID] = mapped_column()


class ExtractionReview(Base):
    """Preserves full history of manual fact reviews, corrections, and rejections."""

    __tablename__ = "extraction_reviews"
    __table_args__ = (
        Index("ix_extraction_reviews_document_id_fact_id", "document_id", "fact_id"),
        Index("ix_extraction_reviews_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    fact_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("financial_facts.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(20))  # accepted, corrected, rejected
    original_value: Mapped[Decimal] = mapped_column(Numeric)
    original_currency: Mapped[str | None] = mapped_column(String(3))
    original_scale: Mapped[str] = mapped_column(String(16))
    original_period_type: Mapped[str] = mapped_column(String(20))
    original_period_label: Mapped[str] = mapped_column(String(40))
    corrected_value: Mapped[Decimal | None] = mapped_column(Numeric)
    corrected_currency: Mapped[str | None] = mapped_column(String(3))
    corrected_scale: Mapped[str | None] = mapped_column(String(16))
    corrected_period_type: Mapped[str | None] = mapped_column(String(20))
    corrected_period_label: Mapped[str | None] = mapped_column(String(40))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class DataQualityIssue(Base):
    """Deterministic anomaly / consistency issue identified in extracted data."""

    __tablename__ = "data_quality_issues"
    __table_args__ = (
        Index("ix_data_quality_issues_user_id_status", "user_id", "status"),
        Index("ix_data_quality_issues_document_id", "document_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    rule_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))  # INFO, WARNING, ERROR
    metric: Mapped[str | None] = mapped_column(String(64))
    period: Mapped[str | None] = mapped_column(String(40))
    description: Mapped[str] = mapped_column(Text)
    related_fact_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    evidence_ids: Mapped[list] = mapped_column(JSONB, server_default="[]")
    status: Mapped[str] = mapped_column(String(20), default="OPEN", server_default="OPEN")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class Scenario(Base):
    """User-controlled deterministic financial calculation scenario based on reported facts."""

    __tablename__ = "scenarios"
    __table_args__ = (Index("ix_scenarios_user_id_created_at", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=True
    )
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(200))
    base_period: Mapped[str] = mapped_column(String(40))
    inputs: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    assumptions: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    calculated_outputs: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    base_facts: Mapped[list] = mapped_column(JSONB, server_default="[]")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()


class AuditEvent(Base):
    """Append-only audit trail recording user and system actions."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_user_id_created_at", "user_id", "created_at"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor_email: Mapped[str | None] = mapped_column(String(320))
    event_type: Mapped[str] = mapped_column(String(50))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(100))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default="{}")
    before_value: Mapped[dict | None] = mapped_column(JSONB)
    after_value: Mapped[dict | None] = mapped_column(JSONB)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created_at()


class WatchlistEntry(Base):
    """Bookmarked company for research organization."""

    __tablename__ = "watchlist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "company_id", name="uq_watchlist_user_company"),
        Index("ix_watchlist_entries_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = _created_at()


class DocumentComparison(Base):
    """Record of a comparison performed between two documents."""

    __tablename__ = "document_comparisons"
    __table_args__ = (Index("ix_document_comparisons_user_id", "user_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    document_a_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    document_b_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    summary: Mapped[dict] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created_at()
