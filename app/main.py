"""FastAPI Payment Gateway Application Entry Point.

Configures application lifespan, database initialization,
structured exception handlers, and API routing.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.api.routes import router
from app.core.config import settings
from app.core.exceptions import GatewayException
from app.db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager: initializes database tables and seeds defaults on startup."""
    init_db()
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Educational Simulation of an Industry Payment Gateway for QA & Reliability Engineering.",
    lifespan=lifespan,
)


@app.exception_handler(GatewayException)
async def gateway_exception_handler(request: Request, exc: GatewayException):
    """Handle all domain exceptions and return standardized error envelopes."""
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_envelope(),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Intercept Pydantic validation errors and format into standard error envelope."""
    errors = exc.errors()
    details = {
        "validation_errors": [
            {
                "field": " -> ".join(str(loc) for loc in err["loc"]),
                "issue": err["msg"],
                "type": err["type"],
            }
            for err in errors
        ]
    }
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "error": {
                "code": "validation_error",
                "message": "Input validation failed. Please check field types and constraints.",
                "details": details,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@app.exception_handler(OperationalError)
async def sqlite_operational_error_handler(request: Request, exc: OperationalError):
    """Handle SQLite database locking errors under high concurrency contention."""
    msg = str(exc)
    if "database is locked" in msg or "busy" in msg:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": {
                    "code": "database_busy",
                    "message": "Database is temporarily busy under concurrent load. Safely retry with your Idempotency-Key.",
                    "details": {"retriable": True},
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "internal_database_error",
                "message": "A database error occurred.",
                "details": {},
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        },
    )


@app.get("/health", tags=["System"])
def health_check():
    """Health status endpoint."""
    return {
        "status": "healthy",
        "service": "payment-gateway-simulator",
        "version": settings.VERSION,
    }


# Register all API endpoints
app.include_router(router)
