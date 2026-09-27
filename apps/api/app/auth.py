"""Anonymous sessions (docs/MVP_SPEC.md §4.1 single-user mode, with explicit owners).

Token: `v1.<session_id>.<issued_at>.<expires_at>.<hmac-sha256>`, signed with APP_SECRET. A token
is accepted only if its signature is valid, it has not expired, and its server-side session row
exists, is unrevoked and unexpired, so a single session can be revoked without rotating the
secret. The session's user id scopes every document query; the client never chooses an owner.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request
from fastapi.params import Depends as DependsParam
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import ratelimit
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.logs import security_event
from app.models import User, UserSession

router = APIRouter(tags=["sessions"])
VERSION = "v1"
INVALID = "Missing or invalid session token"


def _signature(payload: str) -> str:
    secret = get_settings().app_secret.get_secret_value().encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def token_for(session_row: UserSession) -> str:
    issued = int(session_row.created_at.timestamp())
    expires = int(session_row.expires_at.timestamp())
    payload = f"{VERSION}.{session_row.id}.{issued}.{expires}"
    return f"{payload}.{_signature(payload)}"


def start_session(db: Session, user_id: uuid.UUID) -> UserSession:
    """A new session row for the user (the caller commits)."""
    now = datetime.now(UTC).replace(microsecond=0)
    row = UserSession(
        user_id=user_id,
        created_at=now,
        expires_at=now + timedelta(seconds=get_settings().session_ttl_seconds),
    )
    db.add(row)
    db.flush()
    return row


@dataclass(frozen=True)
class Auth:
    user_id: uuid.UUID
    session_id: uuid.UUID


def _reject(request: Request, event: str, message: str = INVALID) -> ApiError:
    security_event(event, request)
    return ApiError(401, "unauthorized", message)


def current_auth(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> Auth:
    token = (authorization or "").removeprefix("Bearer ").strip()
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != VERSION:
        raise _reject(request, "session_invalid")
    payload, signature = ".".join(parts[:4]), parts[4]
    if not hmac.compare_digest(signature, _signature(payload)):
        raise _reject(request, "session_invalid")
    try:  # signed by us, so these parse; guard anyway
        session_id, expires = uuid.UUID(parts[1]), int(parts[3])
    except ValueError:
        raise _reject(request, "session_invalid") from None
    now = datetime.now(UTC)
    if expires <= now.timestamp():
        raise _reject(request, "session_expired", "Session expired")
    row = db.get(UserSession, session_id)
    if row is None:
        raise _reject(request, "session_invalid")
    if row.revoked_at is not None:
        raise _reject(request, "session_revoked", "Session is no longer valid")
    expires_at = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    if expires_at <= now:  # server-side expiry (drivers without tz info return naive UTC)
        raise _reject(request, "session_expired", "Session expired")
    request.state.user_id, request.state.session_id = str(row.user_id), str(row.id)
    return Auth(row.user_id, row.id)


CurrentAuth = Annotated[Auth, Depends(current_auth)]


def current_user_id(auth: CurrentAuth) -> uuid.UUID:
    return auth.user_id


CurrentUserId = Annotated[uuid.UUID, Depends(current_user_id)]
DbSession = Annotated[Session, Depends(get_session)]


def limit_user(bucket: str) -> DependsParam:
    """Route dependency: authenticate, then count the request against the user's bucket.

    Per user rather than per token, so refreshing a session does not reset the count.
    """

    def dependency(request: Request, auth: CurrentAuth) -> None:
        ratelimit.hit(request, bucket, f"user:{auth.user_id}")

    return Depends(dependency)


class SessionToken(BaseModel):
    token: str
    expires_at: datetime


@router.post("/sessions", status_code=201, dependencies=[ratelimit.limit_ip("sessions")])
def create_session(db: DbSession) -> SessionToken:
    """A new anonymous identity. Rate limited per client IP."""
    user = User()
    db.add(user)
    db.flush()
    row = start_session(db, user.id)
    db.commit()
    return SessionToken(token=token_for(row), expires_at=row.expires_at)


@router.post("/sessions/refresh", dependencies=[limit_user("session_refresh")])
def refresh_session(request: Request, auth: CurrentAuth, db: DbSession) -> SessionToken:
    """Swap a valid token for a fresh one (same user), revoking the old session."""
    old = db.get_one(UserSession, auth.session_id, with_for_update=True)
    if old.revoked_at is not None:  # a concurrent refresh won the lock: one token, one refresh
        raise _reject(request, "session_revoked", "Session is no longer valid")
    old.revoked_at = datetime.now(UTC)
    row = start_session(db, auth.user_id)
    db.commit()
    return SessionToken(token=token_for(row), expires_at=row.expires_at)


@router.delete("/sessions/current", status_code=204)
def revoke_session(auth: CurrentAuth, db: DbSession) -> None:
    """Sign out: this token stops working immediately."""
    db.get_one(UserSession, auth.session_id).revoked_at = datetime.now(UTC)
    db.commit()
