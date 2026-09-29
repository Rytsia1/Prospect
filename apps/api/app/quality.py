"""Deterministic Data Quality and Anomaly Detection (PRD Phase 6 §8).

Applies deterministic rules to identify:
- missing data
- duplicate data
- conflicting data
- unit/scale/currency inconsistencies
- large historical changes (configurable threshold)
- accounting consistency / reconciliation mismatches

Supports full anomaly lifecycle: OPEN, ACKNOWLEDGED, RESOLVED, IGNORED.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import quotas
from app.analytics import CONTEXT
from app.audit import record_audit_event
from app.auth import CurrentUserId, limit_user
from app.documents import (
    DbSession,
    FactOut,
    Paragraph,
    _facts,
)
from app.errors import ApiError
from app.extraction import MAX_ABS_VALUE, NON_NEGATIVE
from app.models import (
    DataQualityIssue,
    Document,
    FactStatus,
)
from app.workspace import METRIC_NAMES

router = APIRouter(prefix="/data-quality", tags=["data-quality"])

AnomalySeverity = Literal["INFO", "WARNING", "ERROR"]
AnomalyStatus = Literal["OPEN", "ACKNOWLEDGED", "RESOLVED", "IGNORED"]


class AnomalyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    company_id: uuid.UUID | None
    rule_type: str
    severity: AnomalySeverity
    metric: str | None
    period: str | None
    description: str
    related_fact_ids: list[str]
    evidence_ids: list[str]
    status: AnomalyStatus
    created_at: datetime
    updated_at: datetime


class DataQualitySummary(BaseModel):
    facts_verified_count: int
    items_requiring_review_count: int
    large_changes_count: int
    reconciled_status: str
    open_issues_count: int


class DataQualityResponse(BaseModel):
    summary: DataQualitySummary
    issues: list[AnomalyOut]


class UpdateAnomalyStatusRequest(BaseModel):
    status: AnomalyStatus
    reason: Paragraph | None = None


def detect_document_anomalies(
    session: Session,
    user_id: uuid.UUID,
    documents: list[Document],
    large_change_threshold: Decimal = Decimal("1.0"),  # 100% YoY
) -> list[DataQualityIssue]:
    """Run deterministic data quality checks on facts across the given documents."""
    doc_ids = [d.id for d in documents]
    all_facts = _facts(session, *doc_ids)

    detected: list[DataQualityIssue] = []

    # Map of (document_id, metric, period_label) -> list of facts (to detect duplicates)
    by_doc_metric_period: dict[tuple[uuid.UUID, str, str], list[FactOut]] = {}
    for f in all_facts:
        by_doc_metric_period.setdefault((f.document_id, f.metric, f.period_label), []).append(f)

    # 1. Duplicate data check
    for (d_id, m_key, p_lbl), facts_group in by_doc_metric_period.items():
        if len(facts_group) > 1:
            m_name = METRIC_NAMES.get(m_key, m_key)
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=d_id,
                    rule_type="DUPLICATE_DATA",
                    severity="WARNING",
                    metric=m_key,
                    period=p_lbl,
                    description=(
                        f"Multiple facts extracted for {m_name} in {p_lbl} "
                        "within the same document."
                    ),
                    related_fact_ids=[str(f.id) for f in facts_group],
                    evidence_ids=[str(f.evidence.id) for f in facts_group],
                    status="OPEN",
                )
            )

    # Facts are only ever compared within one company (or one document without a company):
    # the same metric and period of two different companies is not a conflict.
    scope_of = {d.id: d.company_id or d.id for d in documents}
    accepted = [f for f in all_facts if f.status in (FactStatus.ACCEPTED, FactStatus.CORRECTED)]

    # 2. Conflicting data across documents for same metric and period
    by_metric_period: dict[tuple[uuid.UUID, str, str], list[FactOut]] = {}
    for f in accepted:
        key = (scope_of[f.document_id], f.metric, f.period_label)
        by_metric_period.setdefault(key, []).append(f)

    for (_, m_key, p_lbl), facts_group in by_metric_period.items():
        stated = sorted({f.currency or "" for f in facts_group})
        if len(stated) > 1:
            # Same fact, different currencies: never picked or converted, only surfaced.
            m_name = METRIC_NAMES.get(m_key, m_key)
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=facts_group[0].document_id,
                    rule_type="CURRENCY_CONFLICT",
                    severity="ERROR",
                    metric=m_key,
                    period=p_lbl,
                    description=(
                        f"{m_name} in {p_lbl} is reported in different currencies "
                        f"({', '.join(stated)}) across sources. Prospect does not convert "
                        "currencies, so these values are not comparable; check which currency "
                        "each source states."
                    ),
                    related_fact_ids=[str(f.id) for f in facts_group],
                    evidence_ids=[str(f.evidence.id) for f in facts_group],
                    status="OPEN",
                )
            )
            continue
        unique_vals = {(f.value, f.currency) for f in facts_group}
        if len(unique_vals) > 1:
            m_name = METRIC_NAMES.get(m_key, m_key)
            vals_str = ", ".join(f"{v} {c or ''}".strip() for v, c in unique_vals)
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=facts_group[0].document_id,
                    rule_type="CONFLICTING_DATA",
                    severity="ERROR",
                    metric=m_key,
                    period=p_lbl,
                    description=(
                        f"Conflicting values detected across documents for {m_name} in {p_lbl}: "
                        f"{vals_str}."
                    ),
                    related_fact_ids=[str(f.id) for f in facts_group],
                    evidence_ids=[str(f.evidence.id) for f in facts_group],
                    status="OPEN",
                )
            )

    # 3. Unit / currency inconsistency across periods for the same metric
    by_metric: dict[tuple[uuid.UUID, str], list[FactOut]] = {}
    for f in accepted:
        by_metric.setdefault((scope_of[f.document_id], f.metric), []).append(f)

    for (_, m_key), facts_group in by_metric.items():
        currencies = {f.currency for f in facts_group if f.currency}
        if len(currencies) > 1:
            m_name = METRIC_NAMES.get(m_key, m_key)
            curr_str = ", ".join(sorted(currencies))
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=facts_group[0].document_id,
                    rule_type="UNIT_INCONSISTENCY",
                    severity="WARNING",
                    metric=m_key,
                    period=None,
                    description=(
                        f"{m_name} reported in multiple currencies ({curr_str}) across periods."
                    ),
                    related_fact_ids=[str(f.id) for f in facts_group],
                    evidence_ids=[str(f.evidence.id) for f in facts_group],
                    status="OPEN",
                )
            )

    # 4. Large changes check (YoY)
    # Group by metric, sort by fiscal year
    for (_, m_key), facts_group in by_metric.items():
        annual_facts = sorted(
            [f for f in facts_group if f.fiscal_year is not None],
            key=lambda f: f.fiscal_year or 0,
        )
        for i in range(1, len(annual_facts)):
            prev_f = annual_facts[i - 1]
            curr_f = annual_facts[i]
            if (
                curr_f.fiscal_year == (prev_f.fiscal_year or 0) + 1
                and curr_f.currency == prev_f.currency  # across currencies: not comparable
                and prev_f.value != 0
            ):
                diff = CONTEXT.subtract(curr_f.value, prev_f.value)
                ratio = CONTEXT.divide(abs(diff), abs(prev_f.value))
                if ratio >= large_change_threshold:
                    pct = ratio * 100
                    m_name = METRIC_NAMES.get(m_key, m_key)
                    sign = "+" if diff > 0 else "-"
                    detected.append(
                        DataQualityIssue(
                            user_id=user_id,
                            document_id=curr_f.document_id,
                            rule_type="LARGE_CHANGE",
                            severity="WARNING",
                            metric=m_key,
                            period=curr_f.period_label,
                            description=(
                                f"Large change detected in {m_name} from {prev_f.period_label} "
                                f"to {curr_f.period_label} ({sign}{pct:.1f}%)."
                            ),
                            related_fact_ids=[str(prev_f.id), str(curr_f.id)],
                            evidence_ids=[str(prev_f.evidence.id), str(curr_f.evidence.id)],
                            status="OPEN",
                        )
                    )

    # 5. Missing key data check
    # If a document has some facts for FYn, check if key standard metrics are missing
    for d in documents:
        doc_facts = [f for f in all_facts if f.document_id == d.id]
        periods = {f.period_label for f in doc_facts if f.period_label.startswith("FY")}
        key_metrics = ["revenue", "net_income", "total_assets", "total_liabilities", "equity"]
        for p in periods:
            present_metrics = {f.metric for f in doc_facts if f.period_label == p}
            missing = [km for km in key_metrics if km not in present_metrics]
            for m in missing:
                m_name = METRIC_NAMES.get(m, m)
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=d.id,
                        rule_type="MISSING_DATA",
                        severity="INFO",
                        metric=m,
                        period=p,
                        description=f"Key metric '{m_name}' not detected for reporting period {p}.",
                        related_fact_ids=[],
                        evidence_ids=[],
                        status="OPEN",
                    )
                )

    # 6. Accounting consistency check (Assets = Liabilities + Equity)
    scope_periods = {(scope_of[f.document_id], f.period_label) for f in all_facts}
    for scope, p in scope_periods:
        p_facts = {
            f.metric: f
            for f in accepted
            if f.period_label == p and scope_of[f.document_id] == scope
        }
        balance = [p_facts.get(m) for m in ("total_assets", "total_liabilities", "equity")]
        if all(balance) and len({f.currency for f in balance if f}) == 1:
            assets = p_facts["total_assets"].value
            liab = p_facts["total_liabilities"].value
            eq = p_facts["equity"].value
            total_liab_eq = CONTEXT.add(liab, eq)
            diff = CONTEXT.subtract(assets, total_liab_eq)
            if diff != 0:
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=p_facts["total_assets"].document_id,
                        rule_type="ACCOUNTING_CONSISTENCY",
                        severity="WARNING" if abs(diff) <= Decimal(10_000_000) else "ERROR",
                        metric="total_assets",
                        period=p,
                        description=(
                            f"Balance sheet does not reconcile in {p}: Assets ({assets}) ≠ "
                            f"Liabilities + Equity ({total_liab_eq}), difference: {diff}."
                        ),
                        related_fact_ids=[
                            str(p_facts["total_assets"].id),
                            str(p_facts["total_liabilities"].id),
                            str(p_facts["equity"].id),
                        ],
                        evidence_ids=[
                            str(p_facts["total_assets"].evidence.id),
                            str(p_facts["total_liabilities"].evidence.id),
                            str(p_facts["equity"].evidence.id),
                        ],
                        status="OPEN",
                    )
                )

    # 7. Data-level issues: Missing currency, missing scale, suspicious/impossible magnitude/sign
    for f in all_facts:
        m_name = METRIC_NAMES.get(f.metric, f.metric)
        ev_id = [str(f.evidence.id)] if f.evidence else []
        f_id = [str(f.id)]

        if f.currency_status == "inferred":
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=f.document_id,
                    rule_type="CURRENCY_INFERRED",
                    severity="INFO",
                    metric=f.metric,
                    period=f.period_label,
                    description=(
                        f"Currency of '{m_name}' in {f.period_label} ({f.currency}) is inferred "
                        "from other pages of the document, not stated with the value. Confirm it "
                        "in review."
                    ),
                    related_fact_ids=f_id,
                    evidence_ids=ev_id,
                    status="OPEN",
                )
            )

        if f.currency is None:
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=f.document_id,
                    rule_type="MISSING_CURRENCY",
                    severity="WARNING",
                    metric=f.metric,
                    period=f.period_label,
                    description=(
                        f"Fact for '{m_name}' in {f.period_label} lacks a stated currency. "
                        "Currency cannot be inferred."
                    ),
                    related_fact_ids=f_id,
                    evidence_ids=ev_id,
                    status="OPEN",
                )
            )

        if not f.scale:
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=f.document_id,
                    rule_type="MISSING_SCALE",
                    severity="INFO",
                    metric=f.metric,
                    period=f.period_label,
                    description=(
                        f"Fact for '{m_name}' in {f.period_label} has an unstated unit scale."
                    ),
                    related_fact_ids=f_id,
                    evidence_ids=ev_id,
                    status="OPEN",
                )
            )

        if f.metric in NON_NEGATIVE and f.value < 0:
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=f.document_id,
                    rule_type="SUSPICIOUS_VALUE",
                    severity="WARNING",
                    metric=f.metric,
                    period=f.period_label,
                    description=(
                        f"Negative value ({f.value}) reported for inherently non-negative metric "
                        f"'{m_name}' in {f.period_label}. This relationship requires review."
                    ),
                    related_fact_ids=f_id,
                    evidence_ids=ev_id,
                    status="OPEN",
                )
            )

        if abs(f.value) > MAX_ABS_VALUE:
            detected.append(
                DataQualityIssue(
                    user_id=user_id,
                    document_id=f.document_id,
                    rule_type="SUSPICIOUS_VALUE",
                    severity="ERROR",
                    metric=f.metric,
                    period=f.period_label,
                    description=(
                        f"Value for '{m_name}' in {f.period_label} exceeds plausible limits "
                        f"({f.value}). This value requires review."
                    ),
                    related_fact_ids=f_id,
                    evidence_ids=ev_id,
                    status="OPEN",
                )
            )

    # 8. Deterministic impossible structural relationships within the same period
    for scope, p in scope_periods:
        p_accepted = {
            f.metric: f
            for f in accepted
            if f.period_label == p and scope_of[f.document_id] == scope
        }

        def same(a: str, b: str, facts: dict[str, FactOut] = p_accepted) -> bool:
            """Both present and in one currency: no FX conversion exists to compare others."""
            return a in facts and b in facts and facts[a].currency == facts[b].currency

        # Cash > Current Assets
        if same("cash", "current_assets"):
            cash_val = p_accepted["cash"].value
            ca_val = p_accepted["current_assets"].value
            if cash_val > ca_val:
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=p_accepted["cash"].document_id,
                        rule_type="IMPOSSIBLE_RELATIONSHIP",
                        severity="ERROR",
                        metric="cash",
                        period=p,
                        description=(
                            f"Cash and cash equivalents ({cash_val}) exceeds total current assets "
                            f"({ca_val}) in {p}. This relationship requires review."
                        ),
                        related_fact_ids=[
                            str(p_accepted["cash"].id),
                            str(p_accepted["current_assets"].id),
                        ],
                        evidence_ids=[
                            str(p_accepted["cash"].evidence.id),
                            str(p_accepted["current_assets"].evidence.id),
                        ],
                        status="OPEN",
                    )
                )

        # Current Assets > Total Assets
        if same("current_assets", "total_assets"):
            ca_val = p_accepted["current_assets"].value
            ta_val = p_accepted["total_assets"].value
            if ca_val > ta_val:
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=p_accepted["current_assets"].document_id,
                        rule_type="IMPOSSIBLE_RELATIONSHIP",
                        severity="ERROR",
                        metric="current_assets",
                        period=p,
                        description=(
                            f"Total current assets ({ca_val}) exceeds total assets "
                            f"({ta_val}) in {p}. This relationship requires review."
                        ),
                        related_fact_ids=[
                            str(p_accepted["current_assets"].id),
                            str(p_accepted["total_assets"].id),
                        ],
                        evidence_ids=[
                            str(p_accepted["current_assets"].evidence.id),
                            str(p_accepted["total_assets"].evidence.id),
                        ],
                        status="OPEN",
                    )
                )

        # Current Liabilities > Total Liabilities
        if same("current_liabilities", "total_liabilities"):
            cl_val = p_accepted["current_liabilities"].value
            tl_val = p_accepted["total_liabilities"].value
            if cl_val > tl_val:
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=p_accepted["current_liabilities"].document_id,
                        rule_type="IMPOSSIBLE_RELATIONSHIP",
                        severity="ERROR",
                        metric="current_liabilities",
                        period=p,
                        description=(
                            f"Total current liabilities ({cl_val}) exceeds total liabilities "
                            f"({tl_val}) in {p}. This relationship requires review."
                        ),
                        related_fact_ids=[
                            str(p_accepted["current_liabilities"].id),
                            str(p_accepted["total_liabilities"].id),
                        ],
                        evidence_ids=[
                            str(p_accepted["current_liabilities"].evidence.id),
                            str(p_accepted["total_liabilities"].evidence.id),
                        ],
                        status="OPEN",
                    )
                )

        # Operating Income > Gross Profit (when both positive)
        if same("operating_income", "gross_profit"):
            op_val = p_accepted["operating_income"].value
            gp_val = p_accepted["gross_profit"].value
            if op_val > gp_val and gp_val > 0:
                detected.append(
                    DataQualityIssue(
                        user_id=user_id,
                        document_id=p_accepted["operating_income"].document_id,
                        rule_type="UNUSUAL_RELATIONSHIP",
                        severity="WARNING",
                        metric="operating_income",
                        period=p,
                        description=(
                            f"Operating income ({op_val}) exceeds gross profit "
                            f"({gp_val}) in {p}. This relationship requires review."
                        ),
                        related_fact_ids=[
                            str(p_accepted["operating_income"].id),
                            str(p_accepted["gross_profit"].id),
                        ],
                        evidence_ids=[
                            str(p_accepted["operating_income"].evidence.id),
                            str(p_accepted["gross_profit"].evidence.id),
                        ],
                        status="OPEN",
                    )
                )

    return detected


@router.get("", response_model=DataQualityResponse, dependencies=[limit_user("compute")])
def get_data_quality(
    user_id: CurrentUserId,
    session: DbSession,
    document_id: Annotated[uuid.UUID | None, Query()] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
    status: Annotated[AnomalyStatus | None, Query()] = None,
    severity: Annotated[AnomalySeverity | None, Query()] = None,
) -> DataQualityResponse:
    """Retrieve data quality summary and issues for documents/companies owned by user."""
    # Find documents in scope
    query_docs = select(Document).where(Document.user_id == user_id)
    if document_id:
        query_docs = query_docs.where(Document.id == document_id)
    if company_id:
        query_docs = query_docs.where(Document.company_id == company_id)

    docs = list(session.scalars(query_docs).all())
    if document_id and not docs:
        raise ApiError(404, "not_found", "Document not found")

    # Detect issues deterministically
    fresh_issues = detect_document_anomalies(session, user_id, docs)

    # Sync fresh issues into DB if not present. The user-row lock serializes this
    # check-then-insert, so concurrent reads cannot store the same issue twice.
    quotas.lock_user(session, user_id)
    existing = list(
        session.scalars(select(DataQualityIssue).where(DataQualityIssue.user_id == user_id)).all()
    )
    existing_keys = {(i.document_id, i.rule_type, i.metric, i.period): i for i in existing}

    for issue in fresh_issues:
        key = (issue.document_id, issue.rule_type, issue.metric, issue.period)
        if key not in existing_keys:
            session.add(issue)
            existing.append(issue)
            existing_keys[key] = issue

    session.commit()

    # Filter for response
    filtered = existing
    if document_id:
        filtered = [i for i in filtered if i.document_id == document_id]
    if status:
        filtered = [i for i in filtered if i.status == status]
    if severity:
        filtered = [i for i in filtered if i.severity == severity]

    all_facts = _facts(session, *(d.id for d in docs))
    verified_count = sum(
        1 for f in all_facts if f.status in (FactStatus.ACCEPTED, FactStatus.CORRECTED)
    )
    review_count = sum(1 for f in all_facts if f.status == FactStatus.NEEDS_REVIEW)
    large_changes_count = sum(1 for i in filtered if i.rule_type == "LARGE_CHANGE")
    accounting_issues = [i for i in filtered if i.rule_type == "ACCOUNTING_CONSISTENCY"]
    reconciled_status = "Mismatches detected" if accounting_issues else "Balance sheet reconciles"
    open_count = sum(1 for i in filtered if i.status == "OPEN")

    summary = DataQualitySummary(
        facts_verified_count=verified_count,
        items_requiring_review_count=review_count,
        large_changes_count=large_changes_count,
        reconciled_status=reconciled_status,
        open_issues_count=open_count,
    )

    return DataQualityResponse(
        summary=summary,
        issues=[AnomalyOut.model_validate(i, from_attributes=True) for i in filtered],
    )


@router.patch("/{issue_id}", response_model=AnomalyOut)
def update_anomaly_status(
    issue_id: uuid.UUID,
    body: UpdateAnomalyStatusRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> AnomalyOut:
    """Update lifecycle status of an anomaly (OPEN, ACKNOWLEDGED, RESOLVED, IGNORED)."""
    issue = session.scalar(
        select(DataQualityIssue).where(
            DataQualityIssue.id == issue_id, DataQualityIssue.user_id == user_id
        )
    )
    if not issue:
        raise ApiError(404, "not_found", "Data quality issue not found")

    before_status = issue.status
    issue.status = body.status
    issue.updated_at = datetime.now()

    event_type = "ANOMALY_RESOLVED" if body.status == "RESOLVED" else "ANOMALY_ACKNOWLEDGED"
    record_audit_event(
        session=session,
        user_id=user_id,
        event_type=event_type,
        entity_type="anomaly",
        entity_id=str(issue.id),
        metadata={"rule_type": issue.rule_type, "metric": issue.metric, "period": issue.period},
        before={"status": before_status},
        after={"status": body.status},
        reason=body.reason or f"Status changed to {body.status}",
    )
    session.commit()

    return AnomalyOut.model_validate(issue, from_attributes=True)
