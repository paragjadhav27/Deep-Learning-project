"""Uniform, safe error responses. Internal details never reach the client."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from facelens_api.domain.errors import AppError, ErrorCode
from facelens_api.log import get_logger, request_id_var
from facelens_api.schemas.api import ErrorBody, ErrorResponse

log = get_logger(__name__)


def error_response(
    status: int,
    code: str,
    message: str,
    retryable: bool,
    *,
    headers: dict[str, str] | None = None,
    details: dict[str, object] | None = None,
) -> JSONResponse:
    body = ErrorResponse(
        error=ErrorBody(
            code=code,
            message=message,
            retryable=retryable,
            request_id=request_id_var.get(),
            details=details,
        )
    )
    return JSONResponse(
        body.model_dump(mode="json", exclude_none=True), status_code=status, headers=headers
    )


async def _app_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)  # noqa: S101 - registered for AppError only
    return error_response(
        exc.status_code,
        exc.code.value,
        exc.message,
        exc.retryable,
        headers=exc.headers,
        details=exc.details,
    )


async def _validation_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)  # noqa: S101
    # Report locations and messages only; never echo input values back.
    fields = [
        {"loc": ".".join(str(p) for p in e.get("loc", ())), "msg": e.get("msg", "")}
        for e in exc.errors()
    ]
    err = AppError(ErrorCode.VALIDATION_ERROR)
    return error_response(
        err.status_code, err.code.value, err.message, False, details={"fields": fields}
    )


async def _http_error(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)  # noqa: S101
    code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
    message = {404: "Not found.", 405: "Method not allowed."}.get(exc.status_code, "Request error.")
    return error_response(exc.status_code, code, message, False)


async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    log.error("request.unhandled_error", error_type=type(exc).__name__)
    err = AppError(ErrorCode.INTERNAL_ERROR)
    return error_response(err.status_code, err.code.value, err.message, err.retryable)


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(Exception, _unhandled)
