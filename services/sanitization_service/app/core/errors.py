"""The standard error body. Messages are fixed text and never include input."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CORRELATION_HEADER = "X-Correlation-ID"
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}
_PAYLOAD_TOO_LARGE = "The request body is too large."


def error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers={CORRELATION_HEADER: correlation_id},
    )


class ApiError(Exception):
    """An expected failure with a fixed code and message. Never built from input or values."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(code)
        self.status_code = status_code
        self.code = code
        self.message = message


def internal_error(correlation_id: str) -> JSONResponse:
    return error_response(500, "internal_error", "An internal error occurred.", correlation_id)


def payload_too_large(correlation_id: str) -> JSONResponse:
    return error_response(413, "payload_too_large", _PAYLOAD_TOO_LARGE, correlation_id)


def _correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


async def _validation_error(request: Request, _: Exception) -> JSONResponse:
    return error_response(
        422, "validation_error", "The request is not valid.", _correlation_id(request)
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    code = _HTTP_CODES.get(status_code, "http_error")
    message = _PAYLOAD_TOO_LARGE if status_code == 413 else "The request could not be completed."
    return error_response(status_code, code, message, _correlation_id(request))


async def _api_error(request: Request, exc: Exception) -> JSONResponse:
    if not isinstance(exc, ApiError):
        return internal_error(_correlation_id(request))
    return error_response(exc.status_code, exc.code, exc.message, _correlation_id(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
