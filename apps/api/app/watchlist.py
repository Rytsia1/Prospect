"""Watchlist Dashboard and Bookmarks (PRD Phase 6 §12).

Allows users to bookmark companies for fast access and track canonical financial facts
(Revenue, Net Income, deterministic YoY changes).
Strictly factual: NO subjective investment scores or buy/sell recommendations.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.analytics import CONTEXT
from app.audit import record_audit_event
from app.auth import CurrentUserId
from app.documents import (
    DbSession,
    DecimalStr,
    _facts,
)
from app.errors import ApiError
from app.models import (
    Company,
    Document,
    DocumentStatus,
    FactStatus,
    WatchlistEntry,
)

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


class WatchlistCompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company_id: uuid.UUID
    name: str
    ticker: str | None
    country: str | None
    currency: str | None
    latest_period: str | None
    revenue: DecimalStr | None
    revenue_formatted: str | None
    net_income: DecimalStr | None
    net_income_formatted: str | None
    revenue_yoy_change: DecimalStr | None  # ratio (e.g. 0.148 for +14.8%)
    revenue_yoy_change_formatted: str | None  # "+14.8%"
    created_at: datetime


class AddWatchlistRequest(BaseModel):
    company_id: uuid.UUID


def _format_amount(val: Decimal | None, currency: str | None) -> str | None:
    if val is None:
        return None
    curr_prefix = f"{currency} " if currency else ""
    abs_v = abs(val)
    if abs_v >= Decimal("1000000000000"):
        return f"{curr_prefix}{val / Decimal('1000000000000'):.2f}T"
    if abs_v >= Decimal("1000000000"):
        return f"{curr_prefix}{val / Decimal('1000000000'):.2f}B"
    if abs_v >= Decimal("1000000"):
        return f"{curr_prefix}{val / Decimal('1000000'):.2f}M"
    return f"{curr_prefix}{val:,.0f}"


@router.get("", response_model=list[WatchlistCompanyOut])
def get_watchlist(user_id: CurrentUserId, session: DbSession) -> list[WatchlistCompanyOut]:
    """Retrieve bookmarked companies with canonical, factual financial metrics."""
    entries = session.execute(
        select(WatchlistEntry, Company)
        .join(Company, Company.id == WatchlistEntry.company_id)
        .where(WatchlistEntry.user_id == user_id)
        .order_by(WatchlistEntry.created_at.desc())
    ).all()

    items: list[WatchlistCompanyOut] = []
    for entry, company in entries:
        docs = list(
            session.scalars(
                select(Document).where(
                    Document.company_id == company.id,
                    Document.user_id == user_id,
                    Document.status == DocumentStatus.READY,
                )
            ).all()
        )

        latest_period: str | None = None
        rev_val: Decimal | None = None
        curr_str: str | None = company.currency
        ni_val: Decimal | None = None
        yoy_change: Decimal | None = None

        if docs:
            facts = [
                f
                for f in _facts(session, *(d.id for d in docs))
                if f.status in (FactStatus.ACCEPTED, FactStatus.CORRECTED)
            ]
            revenue_facts = sorted(
                [f for f in facts if f.metric == "revenue" and f.fiscal_year is not None],
                key=lambda f: f.fiscal_year or 0,
            )
            ni_facts = {f.period_label: f for f in facts if f.metric == "net_income"}

            if revenue_facts:
                latest_rev = revenue_facts[-1]
                latest_period = latest_rev.period_label
                rev_val = latest_rev.value
                curr_str = latest_rev.currency or curr_str
                if latest_period in ni_facts:
                    ni_val = ni_facts[latest_period].value

                # Deterministic YoY change if previous year exists
                if len(revenue_facts) >= 2:
                    prev_rev = revenue_facts[-2]
                    if (
                        latest_rev.fiscal_year is not None
                        and prev_rev.fiscal_year is not None
                        and latest_rev.fiscal_year == prev_rev.fiscal_year + 1
                        and prev_rev.value != 0
                    ):
                        diff = CONTEXT.subtract(latest_rev.value, prev_rev.value)
                        yoy_change = CONTEXT.divide(diff, abs(prev_rev.value))

        yoy_formatted = None
        if yoy_change is not None:
            pct = yoy_change * 100
            sign = "+" if pct > 0 else ""
            yoy_formatted = f"{sign}{pct:.1f}%"

        items.append(
            WatchlistCompanyOut(
                company_id=company.id,
                name=company.name,
                ticker=company.ticker,
                country=company.country,
                currency=curr_str,
                latest_period=latest_period,
                revenue=rev_val,
                revenue_formatted=_format_amount(rev_val, curr_str),
                net_income=ni_val,
                net_income_formatted=_format_amount(ni_val, curr_str),
                revenue_yoy_change=yoy_change,
                revenue_yoy_change_formatted=yoy_formatted,
                created_at=entry.created_at,
            )
        )

    return items


@router.post("", response_model=WatchlistCompanyOut, status_code=201)
def add_to_watchlist(
    body: AddWatchlistRequest, user_id: CurrentUserId, session: DbSession
) -> WatchlistCompanyOut:
    """Add a company to the watchlist. Duplicate additions are idempotent."""
    company = session.scalar(
        select(Company).where(Company.id == body.company_id, Company.user_id == user_id)
    )
    if not company:
        raise ApiError(404, "not_found", "Company not found")

    existing = session.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user_id, WatchlistEntry.company_id == body.company_id
        )
    )
    if not existing:
        entry = WatchlistEntry(user_id=user_id, company_id=company.id)
        session.add(entry)
        session.flush()

        record_audit_event(
            session=session,
            user_id=user_id,
            event_type="WATCHLIST_UPDATED",
            entity_type="watchlist",
            entity_id=str(company.id),
            metadata={"action": "add", "company_name": company.name},
            reason=f"Added '{company.name}' to watchlist",
        )
        session.commit()
    else:
        entry = existing

    # Return factual info
    return WatchlistCompanyOut(
        company_id=company.id,
        name=company.name,
        ticker=company.ticker,
        country=company.country,
        currency=company.currency,
        latest_period=None,
        revenue=None,
        revenue_formatted=None,
        net_income=None,
        net_income_formatted=None,
        revenue_yoy_change=None,
        revenue_yoy_change_formatted=None,
        created_at=entry.created_at,
    )


@router.delete("/{company_id}", status_code=204)
def remove_from_watchlist(
    company_id: uuid.UUID, user_id: CurrentUserId, session: DbSession
) -> None:
    """Remove a company from the watchlist."""
    entry = session.scalar(
        select(WatchlistEntry).where(
            WatchlistEntry.user_id == user_id, WatchlistEntry.company_id == company_id
        )
    )
    if not entry:
        raise ApiError(404, "not_found", "Company not found on watchlist")

    company = session.scalar(select(Company).where(Company.id == company_id))
    company_name = company.name if company else str(company_id)

    record_audit_event(
        session=session,
        user_id=user_id,
        event_type="WATCHLIST_UPDATED",
        entity_type="watchlist",
        entity_id=str(company_id),
        metadata={"action": "remove", "company_name": company_name},
        reason=f"Removed '{company_name}' from watchlist",
    )
    session.delete(entry)
    session.commit()
