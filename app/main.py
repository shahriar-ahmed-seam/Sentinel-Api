"""FastAPI application: routes, error handling, and hardening.

Status policy:
- 200 success
- 400 invalid JSON / missing or wrong-typed required field
- 422 schema valid but semantically invalid (empty complaint)
- 413 body too large
- 500 internal error (generic body)
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# override=False so the host's env vars and any harness-set values win.
load_dotenv(override=False)

from . import __version__  # noqa: E402
from . import llm  # noqa: E402
from .pipeline import analyze_async  # noqa: E402
from .schemas import AnalyzeRequest  # noqa: E402

logger = logging.getLogger("queuestorm")

MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", "262144"))  # 256 KB default

_CORS_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "*").split(",") if o.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await llm.aclose_async_client()


app = FastAPI(
    title="QueueStorm Investigator",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class EmptyComplaintError(Exception):
    """Raised when `complaint` is present but blank -> HTTP 422."""


@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    cl = request.headers.get("content-length")
    if cl is not None:
        try:
            if int(cl) > MAX_BODY_BYTES:
                return JSONResponse(
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    content={"error": "request body too large"},
                )
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"error": "invalid content-length header"},
            )
    return await call_next(request)


@app.exception_handler(RequestValidationError)
async def on_validation_error(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "invalid or malformed request body"},
    )


@app.exception_handler(EmptyComplaintError)
async def on_empty_complaint(request: Request, exc: EmptyComplaintError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": "complaint must not be empty"},
    )


@app.exception_handler(Exception)
async def on_unhandled(request: Request, exc: Exception):
    logger.exception("unhandled error processing request")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"error": "internal error"},
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze-ticket")
async def analyze_ticket(req: AnalyzeRequest) -> JSONResponse:
    if not req.complaint.strip():
        raise EmptyComplaintError()
    result = await analyze_async(req)
    return JSONResponse(status_code=status.HTTP_200_OK, content=result)
