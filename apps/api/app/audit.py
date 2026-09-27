"""Immutable append-only audit trail (PRD Phase 6 §10).

Tracks meaningful changes to documents, financial facts, quality anomalies,
scenarios, companies, and watchlists. Records actor, before/after values, and reasons.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUserId
from app.db import get_session
from app.models import AuditEvent

router = APIRouter(prefix="/audit", tags=["audit"])
DbSession = Annotated[Session, Depends(get_session)]


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    actor_email: str | None
    event_type: str
    entity_type: str
    entity_id: str
    metadata: dict = Field(default_factory=dict, alias="metadata_json")
    before_value: dict | None
    after_value: dict | None
    reason: str | None
    created_at: datetime


class AuditEventList(BaseModel):
    items: list[AuditEventOut]


def record_audit_event(
    session: Session,
    user_id: uuid.UUID,
    event_type: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    actor_email: str | None = None,
    metadata: dict | None = None,
    before: dict | None = None,
    after: dict | None = None,
    reason: str | None = None,
) -> AuditEvent:
    """Append a new audit event. Audit records are append-only and cannot be mutated or deleted."""
    event = AuditEvent(
        user_id=user_id,
        actor_email=actor_email,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=str(entity_id),
        metadata_json=metadata or {},
        before_value=before,
        after_value=after,
        reason=reason,
    )
    session.add(event)
    session.flush()
    return event


@router.get("", response_model=AuditEventList)
def list_audit_events(
    user_id: CurrentUserId,
    session: DbSession,
    entity_type: Annotated[str | None, Query(max_length=50)] = None,
    entity_id: Annotated[str | None, Query(max_length=100)] = None,
    event_type: Annotated[str | None, Query(max_length=50)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> AuditEventList:
    """Retrieve immutable audit events for the authenticated user."""
    query = (
        select(AuditEvent)
        .where(AuditEvent.user_id == user_id)
        .order_by(AuditEvent.created_at.desc())
    )
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditEvent.entity_id == entity_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    query = query.limit(limit)

    events = session.scalars(query).all()
    return AuditEventList(
        items=[AuditEventOut.model_validate(e, from_attributes=True) for e in events]
    )
