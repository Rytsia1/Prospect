"""Deterministic document comparison (PRD Phase 6 §6).

Compares two financial documents: metadata, structured financial facts, sections,
and text diffs using deterministic algorithms. Every financial diff links to evidence
in both documents.
"""

import difflib
import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analytics import CONTEXT
from app.audit import record_audit_event
from app.auth import CurrentUserId, limit_user
from app.documents import (
    DbSession,
    DecimalStr,
    EvidenceOut,
    _facts,
    _owned_document,
)
from app.models import (
    Document,
    DocumentComparison,
    DocumentPage,
    DocumentSection,
)
from app.workspace import METRIC_NAMES

router = APIRouter(prefix="/documents", tags=["diff"])


class DiffMetadataItem(BaseModel):
    field: str
    label: str
    value_a: str | None
    value_b: str | None
    changed: bool


class FinancialDiffItem(BaseModel):
    metric: str
    metric_name: str
    period: str
    status: Literal["added", "removed", "changed", "unchanged"]
    is_restatement: bool = False
    notes: list[str] = Field(default_factory=list)
    value_a: DecimalStr | None
    currency_a: str | None
    scale_a: str | None
    evidence_a: EvidenceOut | None
    value_b: DecimalStr | None
    currency_b: str | None
    scale_b: str | None
    evidence_b: EvidenceOut | None
    absolute_change: DecimalStr | None
    percentage_change: DecimalStr | None  # ratio (e.g. 0.148 for +14.8%)
    change_formatted: str | None  # e.g. "+14.8%" or "-5.2%"


class SectionDiffItem(BaseModel):
    title: str | None
    ordinal_a: int | None
    ordinal_b: int | None
    page_range_a: str | None
    page_range_b: str | None
    status: Literal["added", "removed", "changed", "unchanged", "uncertain"]


class TextDiffSection(BaseModel):
    section_title: str
    page_a: int | None
    page_b: int | None
    diff_lines: list[str]
    additions: int
    deletions: int


class DocumentDiffResponse(BaseModel):
    document_a_id: uuid.UUID
    document_b_id: uuid.UUID
    document_a_filename: str
    document_b_filename: str
    metadata_diff: list[DiffMetadataItem]
    financial_diff: list[FinancialDiffItem]
    section_diff: list[SectionDiffItem]
    text_diff: list[TextDiffSection]


def _format_pct(change: Decimal | None) -> str | None:
    if change is None:
        return None
    pct = change * 100
    sign = "+" if pct > 0 else ""
    return f"{sign}{pct:.1f}%"


def compute_document_diff(
    session: Session, user_id: uuid.UUID, doc_a: Document, doc_b: Document
) -> DocumentDiffResponse:
    # 1. Metadata diff
    pages_count_a = (
        session.scalar(
            select(func.count(DocumentPage.id)).where(DocumentPage.document_id == doc_a.id)
        )
        or 0
    )
    pages_count_b = (
        session.scalar(
            select(func.count(DocumentPage.id)).where(DocumentPage.document_id == doc_b.id)
        )
        or 0
    )

    metadata_diff: list[DiffMetadataItem] = [
        DiffMetadataItem(
            field="filename",
            label="Filename",
            value_a=doc_a.filename,
            value_b=doc_b.filename,
            changed=doc_a.filename != doc_b.filename,
        ),
        DiffMetadataItem(
            field="fiscal_year",
            label="Fiscal Year",
            value_a=str(doc_a.fiscal_year) if doc_a.fiscal_year else None,
            value_b=str(doc_b.fiscal_year) if doc_b.fiscal_year else None,
            changed=doc_a.fiscal_year != doc_b.fiscal_year,
        ),
        DiffMetadataItem(
            field="company_name",
            label="Company Name",
            value_a=doc_a.company_name,
            value_b=doc_b.company_name,
            changed=(doc_a.company_name or "").lower() != (doc_b.company_name or "").lower(),
        ),
        DiffMetadataItem(
            field="document_type",
            label="Document Type",
            value_a=doc_a.document_type.value,
            value_b=doc_b.document_type.value,
            changed=doc_a.document_type != doc_b.document_type,
        ),
        DiffMetadataItem(
            field="page_count",
            label="Page Count",
            value_a=str(pages_count_a),
            value_b=str(pages_count_b),
            changed=pages_count_a != pages_count_b,
        ),
        DiffMetadataItem(
            field="size_bytes",
            label="File Size",
            value_a=f"{doc_a.size_bytes:,} bytes",
            value_b=f"{doc_b.size_bytes:,} bytes",
            changed=doc_a.size_bytes != doc_b.size_bytes,
        ),
    ]

    # 2. Structured Financial facts diff
    facts_a = {
        (f.metric, f.period_label): f
        for f in _facts(session, doc_a.id)
        if f.status.value in ("accepted", "corrected")
    }
    facts_b = {
        (f.metric, f.period_label): f
        for f in _facts(session, doc_b.id)
        if f.status.value in ("accepted", "corrected")
    }

    all_keys = sorted(
        set(facts_a.keys()) | set(facts_b.keys()),
        key=lambda k: (k[0], k[1]),
    )

    financial_diff: list[FinancialDiffItem] = []
    for metric, period in all_keys:
        fa = facts_a.get((metric, period))
        fb = facts_b.get((metric, period))
        metric_name = METRIC_NAMES.get(metric, metric.replace("_", " ").title())

        if fa and not fb:
            financial_diff.append(
                FinancialDiffItem(
                    metric=metric,
                    metric_name=metric_name,
                    period=period,
                    status="removed",
                    value_a=fa.value,
                    currency_a=fa.currency,
                    scale_a=fa.scale,
                    evidence_a=fa.evidence,
                    value_b=None,
                    currency_b=None,
                    scale_b=None,
                    evidence_b=None,
                    absolute_change=None,
                    percentage_change=None,
                    change_formatted=None,
                )
            )
        elif fb and not fa:
            financial_diff.append(
                FinancialDiffItem(
                    metric=metric,
                    metric_name=metric_name,
                    period=period,
                    status="added",
                    value_a=None,
                    currency_a=None,
                    scale_a=None,
                    evidence_a=None,
                    value_b=fb.value,
                    currency_b=fb.currency,
                    scale_b=fb.scale,
                    evidence_b=fb.evidence,
                    absolute_change=None,
                    percentage_change=None,
                    change_formatted=None,
                )
            )
        elif fa and fb:
            currency_match = fa.currency == fb.currency
            scale_match = fa.scale == fb.scale
            notes: list[str] = []
            if not currency_match:
                notes.append(f"Currency mismatch: {fa.currency} vs {fb.currency}")
            if not scale_match:
                notes.append(f"Scale presentation differs: {fa.scale} vs {fb.scale}")

            is_restatement = False
            if doc_b.fiscal_year and period != f"FY{doc_b.fiscal_year}":
                if fa.value != fb.value or not currency_match:
                    is_restatement = True
                    notes.append(
                        "Restatement or revision of historical period across document versions"
                    )

            if currency_match:
                diff_abs = CONTEXT.subtract(fb.value, fa.value)
                pct_change: Decimal | None = None
                if fa.value != 0:
                    pct_change = CONTEXT.divide(diff_abs, abs(fa.value))
                status: Literal["changed", "unchanged"] = (
                    "unchanged" if diff_abs == 0 and scale_match else "changed"
                )
            else:
                diff_abs = None
                pct_change = None
                status = "changed"

            financial_diff.append(
                FinancialDiffItem(
                    metric=metric,
                    metric_name=metric_name,
                    period=period,
                    status=status,
                    is_restatement=is_restatement,
                    notes=notes,
                    value_a=fa.value,
                    currency_a=fa.currency,
                    scale_a=fa.scale,
                    evidence_a=fa.evidence,
                    value_b=fb.value,
                    currency_b=fb.currency,
                    scale_b=fb.scale,
                    evidence_b=fb.evidence,
                    absolute_change=diff_abs if status == "changed" and currency_match else None,
                    percentage_change=(
                        pct_change if status == "changed" and currency_match else None
                    ),
                    change_formatted=(
                        _format_pct(pct_change)
                        if status == "changed" and currency_match and pct_change is not None
                        else None
                    ),
                )
            )

    # 3. Section diff
    sections_a = list(
        session.scalars(
            select(DocumentSection)
            .where(DocumentSection.document_id == doc_a.id)
            .order_by(DocumentSection.ordinal)
        )
    )
    sections_b = list(
        session.scalars(
            select(DocumentSection)
            .where(DocumentSection.document_id == doc_b.id)
            .order_by(DocumentSection.ordinal)
        )
    )

    by_title_b = {s.title.strip().lower(): s for s in sections_b if s.title}

    section_diff: list[SectionDiffItem] = []
    seen_b_titles: set[str] = set()

    for sa in sections_a:
        if not sa.title:
            section_diff.append(
                SectionDiffItem(
                    title=None,
                    ordinal_a=sa.ordinal,
                    ordinal_b=None,
                    page_range_a=f"pp. {sa.start_page}–{sa.end_page}",
                    page_range_b=None,
                    status="uncertain",
                )
            )
            continue
        norm_title = sa.title.strip().lower()
        sb = by_title_b.get(norm_title)
        if sb:
            seen_b_titles.add(norm_title)
            range_a = f"pp. {sa.start_page}–{sa.end_page}"
            range_b = f"pp. {sb.start_page}–{sb.end_page}"
            changed = range_a != range_b or (sa.end_page - sa.start_page) != (
                sb.end_page - sb.start_page
            )
            section_diff.append(
                SectionDiffItem(
                    title=sa.title,
                    ordinal_a=sa.ordinal,
                    ordinal_b=sb.ordinal,
                    page_range_a=range_a,
                    page_range_b=range_b,
                    status="changed" if changed else "unchanged",
                )
            )
        else:
            section_diff.append(
                SectionDiffItem(
                    title=sa.title,
                    ordinal_a=sa.ordinal,
                    ordinal_b=None,
                    page_range_a=f"pp. {sa.start_page}–{sa.end_page}",
                    page_range_b=None,
                    status="removed",
                )
            )

    for sb in sections_b:
        if not sb.title:
            section_diff.append(
                SectionDiffItem(
                    title=None,
                    ordinal_a=None,
                    ordinal_b=sb.ordinal,
                    page_range_a=None,
                    page_range_b=f"pp. {sb.start_page}–{sb.end_page}",
                    status="uncertain",
                )
            )
        elif sb.title.strip().lower() not in seen_b_titles:
            section_diff.append(
                SectionDiffItem(
                    title=sb.title,
                    ordinal_a=None,
                    ordinal_b=sb.ordinal,
                    page_range_a=None,
                    page_range_b=f"pp. {sb.start_page}–{sb.end_page}",
                    status="added",
                )
            )

    # 4. Deterministic Text diff for matched sections
    text_diff: list[TextDiffSection] = []
    for sa in sections_a:
        if not sa.title:
            continue
        sb = by_title_b.get(sa.title.strip().lower())
        if not sb:
            continue

        text_a_pages = session.scalars(
            select(DocumentPage.text)
            .where(
                DocumentPage.document_id == doc_a.id,
                DocumentPage.page_number.between(
                    sa.start_page, min(sa.start_page + 2, sa.end_page)
                ),
            )
            .order_by(DocumentPage.page_number)
        ).all()
        text_b_pages = session.scalars(
            select(DocumentPage.text)
            .where(
                DocumentPage.document_id == doc_b.id,
                DocumentPage.page_number.between(
                    sb.start_page, min(sb.start_page + 2, sb.end_page)
                ),
            )
            .order_by(DocumentPage.page_number)
        ).all()

        lines_a = "\n".join(text_a_pages).splitlines()
        lines_b = "\n".join(text_b_pages).splitlines()

        if lines_a or lines_b:
            diff = list(
                difflib.unified_diff(
                    lines_a,
                    lines_b,
                    fromfile=f"{doc_a.filename} (p.{sa.start_page})",
                    tofile=f"{doc_b.filename} (p.{sb.start_page})",
                    lineterm="",
                    n=2,
                )
            )
            if diff:
                adds = sum(
                    1 for line in diff if line.startswith("+") and not line.startswith("+++")
                )
                dels = sum(
                    1 for line in diff if line.startswith("-") and not line.startswith("---")
                )
                text_diff.append(
                    TextDiffSection(
                        section_title=sa.title,
                        page_a=sa.start_page,
                        page_b=sb.start_page,
                        diff_lines=diff[:100],  # cap unified diff lines for fast response
                        additions=adds,
                        deletions=dels,
                    )
                )

    # Save comparison record and audit event
    session.add(
        DocumentComparison(
            user_id=user_id,
            document_a_id=doc_a.id,
            document_b_id=doc_b.id,
            summary={
                "financial_diff_count": len(financial_diff),
                "section_diff_count": len(section_diff),
            },
        )
    )
    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="DOCUMENT_COMPARED",
        entity_type="document",
        entity_id=str(doc_a.id),
        metadata={
            "document_a_id": str(doc_a.id),
            "document_b_id": str(doc_b.id),
            "document_a_filename": doc_a.filename,
            "document_b_filename": doc_b.filename,
        },
        reason=f"Compared {doc_a.filename} with {doc_b.filename}",
    )
    session.commit()

    return DocumentDiffResponse(
        document_a_id=doc_a.id,
        document_b_id=doc_b.id,
        document_a_filename=doc_a.filename,
        document_b_filename=doc_b.filename,
        metadata_diff=metadata_diff,
        financial_diff=financial_diff,
        section_diff=section_diff,
        text_diff=text_diff,
    )


class DiffRequest(BaseModel):
    document_a_id: uuid.UUID
    document_b_id: uuid.UUID


@router.post("/diff", response_model=DocumentDiffResponse, dependencies=[limit_user("compute")])
def compare_documents_post(
    body: DiffRequest, user_id: CurrentUserId, session: DbSession
) -> DocumentDiffResponse:
    """Compare two documents owned by the user (POST endpoint)."""
    doc_a = _owned_document(session, user_id, body.document_a_id)
    doc_b = _owned_document(session, user_id, body.document_b_id)
    return compute_document_diff(session, user_id, doc_a, doc_b)


@router.get(
    "/{document_id}/diff", response_model=DocumentDiffResponse, dependencies=[limit_user("compute")]
)
def compare_documents_get(
    document_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
    other_id: Annotated[uuid.UUID, Query(description="Other document ID to compare against")],
) -> DocumentDiffResponse:
    """Compare document_id with other_id owned by the user (GET endpoint)."""
    doc_a = _owned_document(session, user_id, document_id)
    doc_b = _owned_document(session, user_id, other_id)
    return compute_document_diff(session, user_id, doc_a, doc_b)
