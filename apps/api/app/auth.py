"""Anonymous sessions (docs/MVP_SPEC.md §4.1 single-user mode, with explicit owners).

Token: `v1.<session_id>.<issued_at>.<expires_at>.<hmac-sha256>`, signed with APP_SECRET. A token
is accepted only if its signature is valid, it has not expired, and its server-side session row
exists, is unrevoked and unexpired, so a single session can be revoked without rotating the
secret. The session's user id scopes every document query; the client never chooses an owner.

Browsers get the token only as an HttpOnly, SameSite=Strict cookie (never in a response body,
URL or localStorage), so page JavaScript cannot read it. Cookie-authenticated requests that
change state must also pass CSRF checks: a trusted Origin (or Referer) and an X-CSRF-Token
header equal to HMAC(APP_SECRET, "csrf." + session id). Non-browser clients may instead send the
token as `Authorization: Bearer`, which a browser never attaches on its own, so it needs no CSRF
token.
"""

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.params import Depends as DependsParam
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import ratelimit
from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.logs import audit_event, security_event
from app.models import User, UserSession

router = APIRouter(tags=["sessions"])
VERSION = "v1"
INVALID = "Missing or invalid session token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"


def _signature(payload: str) -> str:
    configured = get_settings().app_secret
    if configured is None:  # the API refuses to start without it (app/main.py)
        raise RuntimeError("APP_SECRET is not configured")
    secret = configured.get_secret_value().encode()
    return hmac.new(secret, payload.encode(), hashlib.sha256).hexdigest()


def cookie_name() -> str:
    # __Host-: browsers only accept it Secure, host-only and Path=/ (no Domain widening).
    return ("__Host-" if get_settings().session_cookie_secure else "") + "prospect_session"


def csrf_token(session_id: uuid.UUID) -> str:
    """Bound to the session: useless for another session, replaced on refresh."""
    return _signature(f"csrf.{session_id}")


def request_origin(request: Request) -> str | None:
    """The Origin header, else the Referer's origin; None when the browser sent neither."""
    if origin := request.headers.get("origin"):
        return origin
    scheme, _, rest = request.headers.get("referer", "").partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}" if scheme and rest else None


def origin_trusted(request: Request) -> bool:
    return request_origin(request) in get_settings().origin_list


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
    via_cookie = authorization is None
    token = (
        request.cookies.get(cookie_name(), "")
        if authorization is None
        else authorization.removeprefix("Bearer ").strip()
    )
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != VERSION:
        raise _reject(request, "session_invalid")
    payload, signature = ".".join(parts[:4]), parts[4]
    if not hmac.compare_digest(signature.encode(), _signature(payload).encode()):
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
    if via_cookie and request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not origin_trusted(request) or not hmac.compare_digest(
            sent.encode(), csrf_token(row.id).encode()
        ):
            security_event("csrf_rejected", request, origin=request_origin(request))
            raise ApiError(403, "csrf_failed", "The request could not be verified.")
    return Auth(row.user_id, row.id)


CurrentAuth = Annotated[Auth, Depends(current_auth)]


def current_user_id(auth: CurrentAuth) -> uuid.UUID:
    return auth.user_id


CurrentUserId = Annotated[uuid.UUID, Depends(current_user_id)]
DbSession = Annotated[Session, Depends(get_session)]


def limit_user(bucket: str, ip_bucket: str | None = None) -> DependsParam:
    """Route dependency: authenticate, then count the request against the user's bucket and,
    with ip_bucket, the client IP's too.

    Per user rather than per token, so refreshing a session does not reset the count; per IP as
    well for expensive operations, so opening new anonymous sessions does not either.
    """

    def dependency(request: Request, auth: CurrentAuth) -> None:
        ratelimit.hit(request, bucket, f"user:{auth.user_id}")
        if ip_bucket:
            ratelimit.hit(request, ip_bucket, f"ip:{ratelimit.client_ip(request)}")

    return Depends(dependency)


class SessionInfo(BaseModel):
    """What the browser may know about its session. The token itself is only in the cookie."""

    issued_at: datetime
    expires_at: datetime
    csrf_token: str  # send as X-CSRF-Token on POST/PATCH/PUT/DELETE


def _info(row: UserSession) -> SessionInfo:
    return SessionInfo(
        issued_at=row.created_at, expires_at=row.expires_at, csrf_token=csrf_token(row.id)
    )


def _cookie_attributes() -> dict:
    # SameSite=Strict: every call is a same-origin fetch (the web app proxies /api), so no
    # cross-site flow needs the cookie.
    return {
        "path": "/",
        "secure": get_settings().session_cookie_secure,
        "httponly": True,
        "samesite": "strict",
    }


def _issue(response: Response, row: UserSession) -> SessionInfo:
    response.set_cookie(
        cookie_name(), token_for(row), expires=row.expires_at, **_cookie_attributes()
    )
    return _info(row)


@router.post(
    "/sessions",
    status_code=201,
    dependencies=[ratelimit.limit_ip("sessions"), ratelimit.limit_ip("sessions_daily")],
)
def create_session(request: Request, response: Response, db: DbSession) -> SessionInfo:
    """A new anonymous identity, set as a cookie. Rate limited per client IP."""
    user = User()
    db.add(user)
    db.flush()
    row = start_session(db, user.id)
    db.commit()
    audit_event(
        "session_created", request, user_id=user.id, entity_type="session", entity_id=row.id
    )
    return _issue(response, row)


@router.get("/sessions/current")
def current_session(auth: CurrentAuth, db: DbSession) -> SessionInfo:
    """The session's times and CSRF token (page JavaScript cannot read the HttpOnly cookie)."""
    return _info(db.get_one(UserSession, auth.session_id))


@router.post("/sessions/refresh", dependencies=[limit_user("session_refresh")])
def refresh_session(
    request: Request, response: Response, auth: CurrentAuth, db: DbSession
) -> SessionInfo:
    """Swap a valid session for a fresh one (same user), revoking the old one."""
    old = db.get_one(UserSession, auth.session_id, with_for_update=True)
    if old.revoked_at is not None:  # a concurrent refresh won the lock: one token, one refresh
        raise _reject(request, "session_revoked", "Session is no longer valid")
    old.revoked_at = datetime.now(UTC)
    row = start_session(db, auth.user_id)
    db.commit()
    return _issue(response, row)


@router.delete("/sessions/current", status_code=204)
def revoke_session(request: Request, response: Response, auth: CurrentAuth, db: DbSession) -> None:
    """Sign out: this session stops working immediately and the cookie is cleared."""
    db.get_one(UserSession, auth.session_id).revoked_at = datetime.now(UTC)
    db.commit()
    audit_event(
        "session_revoked",
        request,
        user_id=auth.user_id,
        entity_type="session",
        entity_id=auth.session_id,
    )
    response.delete_cookie(cookie_name(), **_cookie_attributes())
