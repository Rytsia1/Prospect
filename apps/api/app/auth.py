"""Anonymous per-browser identity (docs/MVP_SPEC.md §4.1 single-user mode, with explicit owners).

A session token is `<user_id>.<hmac>` signed with APP_SECRET. The browser keeps it and sends
`Authorization: Bearer <token>`; every document query is scoped to that user id.
"""

import hashlib
import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.errors import ApiError
from app.models import User

# ponytail: stateless, non-expiring anonymous tokens; replace with real auth in Phase 7.
router = APIRouter(tags=["sessions"])


def sign(user_id: uuid.UUID) -> str:
    secret = get_settings().app_secret.get_secret_value().encode()
    signature = hmac.new(secret, str(user_id).encode(), hashlib.sha256).hexdigest()
    return f"{user_id}.{signature}"


def current_user_id(authorization: Annotated[str | None, Header()] = None) -> uuid.UUID:
    token = (authorization or "").removeprefix("Bearer ").strip()
    try:
        user_id = uuid.UUID(token.partition(".")[0])
    except ValueError:
        raise ApiError(401, "unauthorized", "Missing or invalid session token") from None
    if not hmac.compare_digest(token, sign(user_id)):
        raise ApiError(401, "unauthorized", "Missing or invalid session token")
    return user_id


CurrentUserId = Annotated[uuid.UUID, Depends(current_user_id)]


class SessionToken(BaseModel):
    token: str


@router.post("/sessions", status_code=201)
def create_session(session: Annotated[Session, Depends(get_session)]) -> SessionToken:
    user = User()
    session.add(user)
    session.commit()
    return SessionToken(token=sign(user.id))
