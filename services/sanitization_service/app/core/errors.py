"""The standard error body. Messages are fixed text and never include input."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

CORRELATION_HEADER = "X-Correlation-ID"
_HTTP_CODES = {404: "not_found", 405: "method_not_allowed"}


def error_response(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers={CORRELATION_HEADER: correlation_id},
    )


def internal_error(correlation_id: str) -> JSONResponse:
    return error_response(500, "internal_error", "An internal error occurred.", correlation_id)


def _correlation_id(request: Request) -> str:
    return str(request.state.correlation_id)


async def _validation_error(request: Request, _: Exception) -> JSONResponse:
    return error_response(
        422, "validation_error", "The request is not valid.", _correlation_id(request)
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    status_code = exc.status_code if isinstance(exc, StarletteHTTPException) else 500
    code = _HTTP_CODES.get(status_code, "http_error")
    message = "The request could not be completed."
    return error_response(status_code, code, message, _correlation_id(request))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
