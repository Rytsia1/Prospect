"""Deterministic Scenario Analysis Engine (PRD Phase 6 §9).

Pure Decimal calculations for user-controlled mathematical scenarios.
Distinguishes scenarios from reported base facts.
Includes source evidence links and disclaimers.
"""

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Query, Request
from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import quotas
from app.analytics import CONTEXT
from app.audit import record_audit_event
from app.auth import CurrentUserId, limit_user
from app.companies import _owned_company
from app.config import get_settings
from app.documents import (
    DbSession,
    DecimalStr,
    EvidenceOut,
    Line,
    ShortLine,
    _facts,
    _owned_document,
)
from app.errors import ApiError
from app.models import (
    Document,
    FactStatus,
    Scenario,
)

router = APIRouter(prefix="/scenarios", tags=["scenarios"])

SCENARIO_DISCLAIMER = (
    "Scenario values are user-defined calculations and are not forecasts or "
    "investment recommendations."
)


class BaseFactItem(BaseModel):
    metric: str
    metric_name: str
    period: str
    value: DecimalStr
    currency: str | None
    scale: str
    evidence: EvidenceOut | None


class ScenarioCalculationPreview(BaseModel):
    base_period: str
    base_revenue: DecimalStr
    base_net_income: DecimalStr
    base_net_margin: DecimalStr  # ratio (e.g. 0.14)
    growth_adjustment: DecimalStr  # ratio (e.g. 0.05 for +5%)
    margin_adjustment: DecimalStr  # ratio (e.g. 0.01 for +1%)
    scenario_revenue: DecimalStr
    scenario_net_margin: DecimalStr
    scenario_net_income: DecimalStr
    base_facts: list[BaseFactItem]
    disclaimer: str = SCENARIO_DISCLAIMER


def _small_json(value: dict | None) -> dict | None:
    if value is not None and len(json.dumps(value)) > ASSUMPTIONS_MAX_BYTES:
        raise ValueError(f"must be at most {ASSUMPTIONS_MAX_BYTES} bytes as JSON")
    return value


ASSUMPTIONS_MAX_BYTES = 10_000
Assumptions = Annotated[dict | None, AfterValidator(_small_json)]
Margin = Annotated[Decimal, Field(ge=Decimal("-1.0"), le=Decimal("1.0"))]


class ScenarioCalculateRequest(BaseModel):
    document_id: uuid.UUID
    base_period: ShortLine = Field(description="e.g. FY2025")
    growth_adjustment: Decimal = Field(
        default=Decimal("0.0"),
        ge=Decimal("-0.99"),
        le=Decimal("5.0"),
        description="Growth rate adjustment as decimal ratio, e.g. 0.05 for +5%",
    )
    margin_adjustment: Decimal = Field(
        default=Decimal("0.0"),
        ge=Decimal("-1.0"),
        le=Decimal("1.0"),
        description="Net margin adjustment as decimal ratio, e.g. 0.01 for +1%",
    )
    target_margin: Decimal | None = Field(
        default=None,
        ge=Decimal("-1.0"),
        le=Decimal("1.0"),
        description="Explicit scenario net margin",
    )


class ScenarioCreateRequest(BaseModel):
    document_id: uuid.UUID | None = None
    company_id: uuid.UUID | None = None
    name: Annotated[Line, Field(min_length=1)]
    base_period: ShortLine
    growth_adjustment: Decimal = Field(ge=Decimal("-0.99"), le=Decimal("5.0"))
    margin_adjustment: Margin = Decimal("0.0")
    target_margin: Margin | None = None
    assumptions: Assumptions = None


class ScenarioUpdateRequest(BaseModel):
    name: Line | None = None
    growth_adjustment: Decimal | None = Field(default=None, ge=Decimal("-0.99"), le=Decimal("5.0"))
    margin_adjustment: Margin | None = None
    target_margin: Margin | None = None
    assumptions: Assumptions = None


class ScenarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID | None
    company_id: uuid.UUID | None
    name: str
    base_period: str
    inputs: dict
    assumptions: dict
    calculated_outputs: dict
    base_facts: list[dict]
    created_at: datetime
    updated_at: datetime
    disclaimer: str = SCENARIO_DISCLAIMER


def _get_base_financials(
    session: Session, user_id: uuid.UUID, document_id: uuid.UUID, period: str
) -> tuple[Decimal, Decimal, Decimal, list[BaseFactItem]]:
    doc = _owned_document(session, user_id, document_id)
    facts = [
        f
        for f in _facts(session, doc.id)
        if f.period_label == period and f.status in (FactStatus.ACCEPTED, FactStatus.CORRECTED)
    ]
    by_metric = {f.metric: f for f in facts}

    rev_fact = by_metric.get("revenue")
    ni_fact = by_metric.get("net_income")

    if not rev_fact:
        raise ApiError(
            422,
            "missing_base_fact",
            f"Base Revenue fact is required for period '{period}' but was not found in document.",
        )

    # Never a silent zero (AGENTS.md rule 18): a missing net income or a zero revenue leaves the
    # base margin undefined, so there is no scenario to compute.
    if not ni_fact:
        raise ApiError(
            422,
            "missing_base_fact",
            f"Base Net income fact is required for period '{period}' but was not found.",
        )
    if rev_fact.value == 0:
        raise ApiError(422, "undefined_margin", "Base revenue is zero, so the margin is undefined.")
    if rev_fact.currency != ni_fact.currency:  # no FX conversion: a cross-currency margin is wrong
        raise ApiError(
            422,
            "incompatible_currencies",
            f"Revenue ({rev_fact.currency}) and net income ({ni_fact.currency}) are in different "
            "currencies, so the margin is undefined.",
        )
    base_revenue = rev_fact.value
    base_net_income = ni_fact.value
    base_net_margin = CONTEXT.divide(base_net_income, base_revenue)

    base_fact_items = [
        BaseFactItem(
            metric="revenue",
            metric_name="Revenue",
            period=period,
            value=rev_fact.value,
            currency=rev_fact.currency,
            scale=rev_fact.scale,
            evidence=rev_fact.evidence,
        )
    ]
    if ni_fact:
        base_fact_items.append(
            BaseFactItem(
                metric="net_income",
                metric_name="Net income",
                period=period,
                value=ni_fact.value,
                currency=ni_fact.currency,
                scale=ni_fact.scale,
                evidence=ni_fact.evidence,
            )
        )

    return base_revenue, base_net_income, base_net_margin, base_fact_items


def _compute_scenario(
    base_revenue: Decimal,
    base_net_margin: Decimal,
    growth_adj: Decimal,
    margin_adj: Decimal,
    target_margin: Decimal | None,
) -> tuple[Decimal, Decimal, Decimal]:
    # scenario_revenue = base_revenue * (1 + growth_adjustment)
    growth_mult = CONTEXT.add(Decimal(1), growth_adj)
    scenario_revenue = CONTEXT.multiply(base_revenue, growth_mult)

    # scenario_net_margin = target_margin if specified else base_net_margin + margin_adjustment
    if target_margin is not None:
        scenario_net_margin = target_margin
    else:
        scenario_net_margin = CONTEXT.add(base_net_margin, margin_adj)

    # scenario_net_income = scenario_revenue * scenario_net_margin
    scenario_net_income = CONTEXT.multiply(scenario_revenue, scenario_net_margin)

    return scenario_revenue, scenario_net_margin, scenario_net_income


@router.post(
    "/calculate", response_model=ScenarioCalculationPreview, dependencies=[limit_user("compute")]
)
def calculate_scenario_preview(
    body: ScenarioCalculateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ScenarioCalculationPreview:
    """Preview mathematical scenario calculations without persisting."""
    base_rev, base_ni, base_margin, base_facts = _get_base_financials(
        session, user_id, body.document_id, body.base_period
    )
    scen_rev, scen_margin, scen_ni = _compute_scenario(
        base_rev, base_margin, body.growth_adjustment, body.margin_adjustment, body.target_margin
    )
    return ScenarioCalculationPreview(
        base_period=body.base_period,
        base_revenue=base_rev,
        base_net_income=base_ni,
        base_net_margin=base_margin,
        growth_adjustment=body.growth_adjustment,
        margin_adjustment=body.margin_adjustment,
        scenario_revenue=scen_rev,
        scenario_net_margin=scen_margin,
        scenario_net_income=scen_ni,
        base_facts=base_facts,
    )


@router.post("", response_model=ScenarioOut, status_code=201, dependencies=[limit_user("writes")])
def create_scenario(
    request: Request,
    body: ScenarioCreateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ScenarioOut:
    """Save a user-defined scenario."""
    if not body.document_id and not body.company_id:
        raise ApiError(422, "missing_target", "Either document_id or company_id must be provided")
    if body.company_id:  # every id the client names is owned, not only the document's
        _owned_company(session, user_id, body.company_id)
    limit = get_settings().quota_max_scenarios
    quotas.check_count(request, session, user_id, Scenario, limit, "scenarios")

    target_doc_id = body.document_id
    if not target_doc_id and body.company_id:
        first_doc = session.scalar(
            select(Document).where(
                Document.user_id == user_id, Document.company_id == body.company_id
            )
        )
        if not first_doc:
            raise ApiError(
                404, "no_documents", "Company has no associated documents for baseline data"
            )
        target_doc_id = first_doc.id

    assert target_doc_id is not None
    base_rev, base_ni, base_margin, base_facts = _get_base_financials(
        session, user_id, target_doc_id, body.base_period
    )
    scen_rev, scen_margin, scen_ni = _compute_scenario(
        base_rev, base_margin, body.growth_adjustment, body.margin_adjustment, body.target_margin
    )

    inputs = {
        "growth_adjustment": str(body.growth_adjustment),
        "margin_adjustment": str(body.margin_adjustment),
        "target_margin": str(body.target_margin) if body.target_margin is not None else None,
    }
    outputs = {
        "base_revenue": str(base_rev),
        "base_net_income": str(base_ni),
        "base_net_margin": str(base_margin),
        "scenario_revenue": str(scen_rev),
        "scenario_net_margin": str(scen_margin),
        "scenario_net_income": str(scen_ni),
    }
    base_facts_data = [
        {
            "metric": f.metric,
            "period": f.period,
            "value": str(f.value),
            "currency": f.currency,
            "scale": f.scale,
            "page_number": f.evidence.page_number if f.evidence else None,
        }
        for f in base_facts
    ]

    scenario = Scenario(
        user_id=user_id,
        document_id=target_doc_id,  # the facts' source: deleting it deletes the scenario
        company_id=body.company_id,
        name=body.name,
        base_period=body.base_period,
        inputs=inputs,
        assumptions=body.assumptions or {},
        calculated_outputs=outputs,
        base_facts=base_facts_data,
    )
    session.add(scenario)
    session.flush()

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="SCENARIO_CREATED",
        entity_type="scenario",
        entity_id=str(scenario.id),
        metadata={"name": scenario.name, "base_period": scenario.base_period},
        after=outputs,
        reason=f"Created scenario '{scenario.name}'",
    )
    session.commit()

    return ScenarioOut.model_validate(scenario, from_attributes=True)


@router.get("", response_model=list[ScenarioOut])
def list_scenarios(
    user_id: CurrentUserId,
    session: DbSession,
    document_id: Annotated[uuid.UUID | None, Query()] = None,
    company_id: Annotated[uuid.UUID | None, Query()] = None,
) -> list[ScenarioOut]:
    """List saved scenarios for user, optionally filtered by document or company."""
    query = select(Scenario).where(Scenario.user_id == user_id)
    if document_id:
        query = query.where(Scenario.document_id == document_id)
    if company_id:
        query = query.where(Scenario.company_id == company_id)
    query = query.order_by(Scenario.created_at.desc())

    scenarios = session.scalars(query).all()
    return [ScenarioOut.model_validate(s, from_attributes=True) for s in scenarios]


@router.get("/{scenario_id}", response_model=ScenarioOut)
def get_scenario(
    scenario_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
) -> ScenarioOut:
    """Retrieve single scenario by ID."""
    scenario = session.scalar(
        select(Scenario).where(Scenario.id == scenario_id, Scenario.user_id == user_id)
    )
    if not scenario:
        raise ApiError(404, "not_found", "Scenario not found")
    return ScenarioOut.model_validate(scenario, from_attributes=True)


@router.patch("/{scenario_id}", response_model=ScenarioOut)
def update_scenario(
    scenario_id: uuid.UUID,
    body: ScenarioUpdateRequest,
    user_id: CurrentUserId,
    session: DbSession,
) -> ScenarioOut:
    """Update scenario assumptions/inputs and recalculate deterministic outputs."""
    scenario = session.scalar(
        select(Scenario).where(Scenario.id == scenario_id, Scenario.user_id == user_id)
    )
    if not scenario:
        raise ApiError(404, "not_found", "Scenario not found")

    before_outputs = scenario.calculated_outputs

    if body.name is not None:
        scenario.name = body.name
    if body.assumptions is not None:
        scenario.assumptions = body.assumptions

    inputs = dict(scenario.inputs)
    if body.growth_adjustment is not None:
        inputs["growth_adjustment"] = str(body.growth_adjustment)
    if body.margin_adjustment is not None:
        inputs["margin_adjustment"] = str(body.margin_adjustment)
    if body.target_margin is not None:
        inputs["target_margin"] = str(body.target_margin)

    # Recalculate
    growth_adj = Decimal(inputs["growth_adjustment"])
    margin_adj = Decimal(inputs["margin_adjustment"])
    target_margin = Decimal(inputs["target_margin"]) if inputs.get("target_margin") else None

    base_rev = Decimal(scenario.calculated_outputs["base_revenue"])
    base_margin = Decimal(scenario.calculated_outputs["base_net_margin"])

    scen_rev, scen_margin, scen_ni = _compute_scenario(
        base_rev, base_margin, growth_adj, margin_adj, target_margin
    )

    outputs = dict(scenario.calculated_outputs)
    outputs["scenario_revenue"] = str(scen_rev)
    outputs["scenario_net_margin"] = str(scen_margin)
    outputs["scenario_net_income"] = str(scen_ni)

    scenario.inputs = inputs
    scenario.calculated_outputs = outputs
    scenario.updated_at = datetime.now()

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="SCENARIO_UPDATED",
        entity_type="scenario",
        entity_id=str(scenario.id),
        metadata={"name": scenario.name},
        before=before_outputs,
        after=outputs,
        reason=f"Updated inputs for scenario '{scenario.name}'",
    )
    session.commit()

    return ScenarioOut.model_validate(scenario, from_attributes=True)


@router.delete("/{scenario_id}", status_code=204)
def delete_scenario(
    scenario_id: uuid.UUID,
    user_id: CurrentUserId,
    session: DbSession,
) -> None:
    """Delete a scenario."""
    scenario = session.scalar(
        select(Scenario).where(Scenario.id == scenario_id, Scenario.user_id == user_id)
    )
    if not scenario:
        raise ApiError(404, "not_found", "Scenario not found")

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="SCENARIO_DELETED",
        entity_type="scenario",
        entity_id=str(scenario.id),
        metadata={"name": scenario.name},
        before=scenario.calculated_outputs,
        reason=f"Deleted scenario '{scenario.name}'",
    )
    session.delete(scenario)
    session.commit()
