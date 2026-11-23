import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.config import settings
from app.core.exceptions import AppException
from app.utils import send_response

logger = logging.getLogger(__name__)


def error_detail(exc: Exception) -> str:
    if settings.APP_ENV == "development":
        return str(exc)
    return ""


async def app_exception_handler(request: Request, exc: AppException):
    return send_response(exc.status_code, exc.message, error=exc.error, headers=exc.headers)


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return send_response(exc.status_code, str(exc.detail), headers=getattr(exc, "headers", None))


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = [
        {
            "field": ".".join(str(part) for part in err["loc"][1:]),
            "message": err["msg"],
        }
        for err in exc.errors()
    ]
    return send_response(status.HTTP_422_UNPROCESSABLE_CONTENT, "Validation failed", error=errors)


async def database_exception_handler(request: Request, exc: SQLAlchemyError):
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return send_response(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Database is unavailable",
        error=error_detail(exc),
    )


async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return send_response(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "Internal server error",
        error=error_detail(exc),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppException, app_exception_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(SQLAlchemyError, database_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
