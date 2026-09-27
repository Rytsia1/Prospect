import json
import logging
from typing import Any


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


def security_event(event: str, request: Any = None, **fields: object) -> None:
    """A structured security/resource event (rate_limit_exceeded, quota_exceeded, ...).

    Carries the request id and the authenticated user/session when known. Never pass tokens,
    signed URLs, secrets, document text or evidence content.
    """
    state = getattr(request, "state", None)
    context = {
        "event": event,
        "request_id": getattr(state, "request_id", None),
        "user_id": getattr(state, "user_id", None),
        "session_id": getattr(state, "session_id", None),
    }
    _security.warning(event, extra={"fields": {k: v for k, v in (context | fields).items() if v}})
