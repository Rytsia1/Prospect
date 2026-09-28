import logging
import re
import time
import uuid
from collections.abc import Mapping
from http import HTTPStatus

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends, FastAPI, Request
from fastapi.dependencies.models import Dependant
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DataError, IntegrityError, OperationalError
from starlette.exceptions import HTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import (
    audit,
    auth,
    companies,
    diff,
    documents,
    financials,
    quality,
    reviews,
    scenarios,
    watchlist,
)
from app.auth import CSRF_HEADER, SAFE_METHODS, request_origin
from app.config import api_problems, get_settings
from app.errors import ApiError
from app.logs import configure_logging, security_event

API_V1_PREFIX = "/api/v1"  # docs/API_SPEC.yaml `servers`; resource routers mount here.
# Accepted client request ids; anything else is replaced, so ids are safe to log and echo.
REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


settings = get_settings()
if problems := api_problems(settings):  # fail closed before serving anything
    raise RuntimeError("API configuration: " + "; ".join(problems))
configure_logging(settings.log_level)
log = logging.getLogger("prospect.api")
production = settings.environment == "production"


def _query_names(dependant: Dependant) -> frozenset[str]:
    names = {p.alias for p in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _query_names(sub)
    return frozenset(names)


def reject_unknown_query(request: Request) -> None:
    """A misspelled or unsupported filter is an error, never silently ignored."""
    dependant = getattr(request.scope.get("route"), "dependant", None)
    unknown = set(request.query_params) - _query_names(dependant) if dependant else set()
    if unknown:
        name = min(unknown)[:40]  # echoed in a JSON error only (nosniff, CSP none)
        raise ApiError(400, "unknown_parameter", f"Unknown query parameter: {name}")


# Hiding the docs only reduces attack surface; nothing relies on it.
app = FastAPI(
    title="Prospect API",
    version="0.1.0",
    docs_url=None if production else "/docs",
    redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
    dependencies=[Depends(reject_unknown_query)],
)
app.include_router(auth.router, prefix=API_V1_PREFIX)
app.include_router(documents.router, prefix=API_V1_PREFIX)
app.include_router(financials.router, prefix=API_V1_PREFIX)
app.include_router(diff.router, prefix=API_V1_PREFIX)
app.include_router(reviews.router, prefix=API_V1_PREFIX)
app.include_router(quality.router, prefix=API_V1_PREFIX)
app.include_router(scenarios.router, prefix=API_V1_PREFIX)
app.include_router(companies.router, prefix=API_V1_PREFIX)
app.include_router(watchlist.router, prefix=API_V1_PREFIX)
app.include_router(audit.router, prefix=API_V1_PREFIX)


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: list | None = None


class ErrorResponse(BaseModel):
    """Every non-2xx response has this shape."""

    error: ErrorBody


def _error(
    request: Request,
    status: int,
    code: str,
    message: str,
    details=None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details)
    )
    return JSONResponse(
        body.model_dump(exclude_none=True),
        status_code=status,
        headers={"X-Request-ID": request_id, **(headers or {})},
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or HTTPStatus(exc.status_code).phrase.lower().replace(
        " ", "_"
    )
    return _error(request, exc.status_code, code, str(exc.detail), headers=exc.headers)


@app.exception_handler(IntegrityError)
async def conflict(request: Request, exc: IntegrityError) -> JSONResponse:
    # A unique or reference constraint refused the write (e.g. two concurrent creates).
    return _error(request, 409, "conflict", "The request conflicts with existing data.")


@app.exception_handler(DataError)
async def invalid_value(request: Request, exc: DataError) -> JSONResponse:
    # The database refused a value the schemas let through (out of range): the client's input.
    return _error(request, 422, "invalid_value", "A value is out of the supported range.")


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    # Where and why only: the rejected input itself is not echoed back.
    details = [{"loc": e["loc"], "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return _error(
        request, 422, "validation_error", "Request validation failed", jsonable_encoder(details)
    )


# Every API response is JSON (or an export download): never framed, cached, sniffed, or
# given a referrer.
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",  # financial data must not sit in shared or browser caches
}
if production:  # production is HTTPS only (the platform terminates TLS)
    SECURITY_HEADERS["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"


class BodyLimit:
    """Refuse request bodies over MAX_REQUEST_BODY_BYTES before they are read, let alone
    parsed: FastAPI parses the body before authentication runs, so this also bounds what an
    anonymous client can make the API hold in memory. Declared lengths are refused up front;
    chunked bodies are counted while they stream in."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        declared = dict(scope["headers"]).get(b"content-length", b"0")
        if not declared.isdigit() or int(declared) > self.max_bytes:
            return await _too_large(scope, receive, send)
        received = 0

        async def counted() -> Message:
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > self.max_bytes:  # surfaces through FastAPI's handler as a 413
                raise HTTPException(413, "Request body too large.")
            return message

        await self.app(scope, counted, send)


async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
    request = Request(scope, receive)  # request_context (outside) already gave it a request id
    await _error(request, 413, "payload_too_large", "Request body too large.")(scope, receive, send)


# Inside request_context (added before it): the route reads the counted body directly, and
# refusals carry the request id and security headers like every other response.
app.add_middleware(BodyLimit, max_bytes=settings.max_request_body_bytes)


@app.middleware("http")
async def request_context(request: Request, call_next):
    sent_id = request.headers.get("X-Request-ID", "")
    request.state.request_id = sent_id if REQUEST_ID.match(sent_id) else str(uuid.uuid4())
    start = time.perf_counter()
    fields = {
        "request_id": request.state.request_id,
        "method": request.method,
        "path": request.url.path,
    }
    origin = request_origin(request)
    try:
        if request.method not in SAFE_METHODS and origin and origin not in settings.origin_list:
            # Sent by a page we do not serve: CSRF, including login CSRF on POST /sessions.
            # Cookie requests without any Origin/Referer are refused in app/auth.py.
            security_event("csrf_rejected", request, origin=origin[:100])
            response = _error(request, 403, "csrf_failed", "The request could not be verified.")
        else:
            response = await call_next(request)
    except (OperationalError, BotoCoreError, ClientError):
        # Database or storage unreachable: temporary. Details stay in the logs.
        log.exception("dependency unavailable", extra={"fields": fields})
        response = _error(request, 503, "service_unavailable", "Service temporarily unavailable.")
    except Exception:
        # Answer here, inside CORS, so browsers can read the error. Details stay in the logs.
        log.exception("request failed", extra={"fields": fields})
        response = _error(request, 500, "internal_error", "Internal server error")
    response.headers["X-Request-ID"] = request.state.request_id
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    fields |= {
        "session_id": getattr(request.state, "session_id", None),  # an id, never the token
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
    }
    log.info("request", extra={"fields": fields})
    return response


# Added last so it is the outermost middleware: every response, errors included, gets CORS.
# Exact configured origins (never reflected) and no credentials: browsers reach the API through
# the web app's same-origin /api proxy, so the cookie never crosses origins. CORS only serves
# Bearer clients on a trusted origin.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", CSRF_HEADER, "X-Request-ID"],
    # Content-Disposition: export filenames. Retry-After: when a rate limit resets.
    expose_headers=["X-Request-ID", "Content-Disposition", "Retry-After"],
    max_age=600,
)


class Health(BaseModel):
    status: str


@app.get("/health")
def health() -> Health:
    # Liveness only: must stay cheap (ARCHITECTURE §9).
    return Health(status="ok")
