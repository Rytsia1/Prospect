import json
import logging
import uuid
from typing import Any

from sqlalchemy import insert
from sqlalchemy.exc import SQLAlchemyError


class JsonFormatter(logging.Formatter):
    """One JSON object per line; pass structured fields via `extra={"fields": {...}}`."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": self.formatTime(record),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)


_security = logging.getLogger("prospect.security")
_audit = logging.getLogger("prospect.audit")

# Security events that also belong in the user's audit trail when the user is known.
AUDITED = {"authorization_denied", "rate_limit_exceeded", "quota_exceeded", "csrf_rejected"}


def _context(request: Any) -> dict[str, Any]:
    state = getattr(request, "state", None)
    return {
        "request_id": getattr(state, "request_id", None),
        "user_id": getattr(state, "user_id", None),
        "session_id": getattr(state, "session_id", None),
    }


def security_event(event: str, request: Any = None, **fields: Any) -> None:
    """A structured security/resource event (rate_limit_exceeded, quota_exceeded, ...).

    Carries the request id and the authenticated user/session when known. Never pass tokens,
    cookies, signed URLs, secrets, document text or evidence content.
    """
    entry = {k: v for k, v in ({"event": event} | _context(request) | fields).items() if v}
    _security.warning(event, extra={"fields": entry})
    if event in AUDITED and entry.get("user_id"):
        audit_event(event, request, result="denied", log=False, **fields)


def audit_event(
    event: str,
    request: Any = None,
    *,
    user_id: object = None,
    entity_type: str = "document",
    entity_id: object = None,
    result: str = "success",
    log: bool = True,
    **fields: object,
) -> None:
    """Append to the audit trail (audit_events) in its own transaction, so a denial is recorded
    even though its request fails. Metadata only (ids, counts, reasons), never content.

    Readable only by its own user (GET /audit); no endpoint updates or deletes audit rows.
    """
    from app.db import engine  # lazily: logging is configured before the database exists
    from app.models import AuditEvent

    context = _context(request)
    user = user_id or context.pop("user_id") or fields.pop("user_id", None)
    if not user:
        return  # anonymous events (per-IP rate limits) stay in the security log only
    entity = entity_id or fields.get("document_id")
    metadata = {k: str(v) for k, v in (context | fields | {"result": result}).items() if v}
    if log:
        _audit.info(event, extra={"fields": {"event": event, "user_id": str(user)} | metadata})
    try:
        with engine.begin() as connection:
            connection.execute(
                insert(AuditEvent).values(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(str(user)),
                    event_type=event,
                    entity_type=entity_type if entity else "session",
                    entity_id=str(entity or context.get("session_id") or ""),
                    metadata_json=metadata,
                )
            )
    except SQLAlchemyError:
        # The user's request is not failed for its audit row; the event stays in this log.
        _audit.exception(
            "audit write failed",
            extra={"fields": {"event": event, "user_id": str(user)} | metadata},
        )
