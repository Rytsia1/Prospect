import logging
import time
import uuid
from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

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
from app.config import get_settings
from app.logs import configure_logging

API_V1_PREFIX = "/api/v1"  # docs/API_SPEC.yaml `servers`; resource routers mount here.


settings = get_settings()
configure_logging(settings.log_level)
log = logging.getLogger("prospect.api")

app = FastAPI(title="Prospect API", version="0.1.0")
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


def _error(request: Request, status: int, code: str, message: str, details=None) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, request_id=request_id, details=details)
    )
    return JSONResponse(
        body.model_dump(exclude_none=True), status_code=status, headers={"X-Request-ID": request_id}
    )


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
    code = getattr(exc, "code", None) or HTTPStatus(exc.status_code).phrase.lower().replace(
        " ", "_"
    )
    return _error(request, exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    details = jsonable_encoder(exc.errors())
    return _error(request, 422, "validation_error", "Request validation failed", details)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    start = time.perf_counter()
    fields = {
        "request_id": request.state.request_id,
        "method": request.method,
        "path": request.url.path,
    }
    try:
        response = await call_next(request)
    except Exception:
        # Answer here, inside CORS, so browsers can read the error. Details stay in the logs.
        log.exception("request failed", extra={"fields": fields})
        response = _error(request, 500, "internal_error", "Internal server error")
    response.headers["X-Request-ID"] = request.state.request_id
    fields |= {
        "status": response.status_code,
        "duration_ms": round((time.perf_counter() - start) * 1000, 1),
    }
    log.info("request", extra={"fields": fields})
    return response


# Added last so it is the outermost middleware: every response, errors included, gets CORS.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "Content-Disposition"],  # export filenames
)


class Health(BaseModel):
    status: str


@app.get("/health")
def health() -> Health:
    # Liveness only: must stay cheap (ARCHITECTURE §9).
    return Health(status="ok")
