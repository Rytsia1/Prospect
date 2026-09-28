"""Server-side fixed-window rate limiting, shared by every API instance.

Counters live in PostgreSQL (already required and shared by all instances); one atomic upsert per
request, so concurrent requests on different instances cannot both slip under the limit.
Limits come from settings as "<requests>/<window seconds>" (RATE_LIMIT_*). Session creation
counts per client IP; authenticated endpoints per user and, for uploads, completion and export,
per client IP too (app/auth.limit_user), so a fresh anonymous session does not reset them.

Client IP: browsers reach the API through the web app's proxy (apps/web/middleware.ts), which
sends the visitor's IP in X-Prospect-Client-IP together with TRUSTED_PROXY_SECRET. Only a request
carrying that secret may name an IP; any other request (a direct client, however it sets
X-Forwarded-For / X-Real-IP / Forwarded) is counted by its TCP peer address.

ponytail: one Postgres upsert per limited request; move the counters to Redis (INCR + EXPIRE)
if that write load ever shows up in database metrics.
"""

import hmac
import ipaddress
import math
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.params import Depends as DependsParam
from sqlalchemy.dialects.postgresql import insert

from app.config import get_settings
from app.db import engine
from app.errors import ApiError
from app.logs import security_event
from app.models import RateLimitCounter


def rate(bucket: str) -> tuple[int, int]:
    """(requests, window seconds) for a bucket, from RATE_LIMIT_<BUCKET>."""
    requests, seconds = getattr(get_settings(), f"rate_limit_{bucket}").split("/")
    return int(requests), int(seconds)


def hit(request: Request, bucket: str, subject: str) -> None:
    """Count one request; raise 429 with Retry-After once the window's limit is passed."""
    limit, window = rate(bucket)
    now = datetime.now(UTC).timestamp()
    start = int(now // window) * window
    statement = (
        insert(RateLimitCounter)
        .values(
            key=f"{bucket}:{subject}:{start}",
            count=1,
            expires_at=datetime.fromtimestamp(start + window, UTC),
        )
        .on_conflict_do_update(index_elements=["key"], set_={"count": RateLimitCounter.count + 1})
        .returning(RateLimitCounter.count)
    )
    with engine.begin() as connection:  # its own transaction: counts even if the request fails
        count: int = connection.execute(statement).scalar_one()
    if count > limit:
        retry_after = max(1, math.ceil(start + window - now))
        security_event("rate_limit_exceeded", request, bucket=bucket, retry_after=retry_after)
        raise ApiError(
            429, "rate_limited", "Rate limit exceeded.", headers={"Retry-After": str(retry_after)}
        )


PROXY_SECRET_HEADER, CLIENT_IP_HEADER = "X-Prospect-Proxy-Secret", "X-Prospect-Client-IP"


def client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    secret = get_settings().trusted_proxy_secret
    sent = request.headers.get(PROXY_SECRET_HEADER, "")
    # bytes: compare_digest refuses non-ASCII str, and header values can be any latin-1 text
    if secret is None or not hmac.compare_digest(sent.encode(), secret.get_secret_value().encode()):
        return peer
    try:  # from our proxy: still only a well-formed address is accepted
        return str(ipaddress.ip_address(request.headers.get(CLIENT_IP_HEADER, "").strip()))
    except ValueError:
        return peer


def limit_ip(bucket: str) -> DependsParam:
    """Route dependency for unauthenticated endpoints: count per client IP."""

    def dependency(request: Request) -> None:
        hit(request, bucket, f"ip:{client_ip(request)}")

    return Depends(dependency)
