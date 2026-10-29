import enum
from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ErrorCode(enum.StrEnum):
    VALIDATION_ERROR = "validation_error"
    UNAUTHORIZED = "unauthorized"
    FORBIDDEN = "forbidden"
    CHAT_MEMBER_REQUIRED = "chat_member_required"
    NOT_FOUND = "not_found"
    DUPLICATE_CHAT = "duplicate_chat"
    CONFLICT = "conflict"
    FILE_TOO_LARGE = "file_too_large"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    DEGRADED = "degraded"
    INTERNAL_ERROR = "internal_error"


class ApiError(Exception):
    def __init__(self, status: int, code: ErrorCode, message: str, details: dict[str, Any] | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(message)


def unauthorized(message: str = "Требуется авторизация") -> ApiError:
    return ApiError(401, ErrorCode.UNAUTHORIZED, message)


def forbidden(message: str = "Недостаточно прав", code: ErrorCode = ErrorCode.FORBIDDEN) -> ApiError:
    return ApiError(403, code, message)


def not_found(entity: str = "Объект") -> ApiError:
    return ApiError(404, ErrorCode.NOT_FOUND, f"{entity} не найден")


def bad_request(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(400, ErrorCode.VALIDATION_ERROR, message, details)


def conflict(message: str, code: ErrorCode = ErrorCode.CONFLICT) -> ApiError:
    return ApiError(409, code, message)


def too_large(message: str = "Файл слишком большой") -> ApiError:
    return ApiError(413, ErrorCode.FILE_TOO_LARGE, message)


def rate_limited(retry_after: int) -> ApiError:
    err = ApiError(429, ErrorCode.RATE_LIMITED, "Слишком много запросов")
    err.details = {"retry_after": retry_after}
    return err


def upstream(message: str = "Внешний сервис недоступен") -> ApiError:
    return ApiError(502, ErrorCode.UPSTREAM_ERROR, message)


def _body(status: int, code: str, message: str, details: dict[str, Any]) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        headers = {}
        if exc.code == ErrorCode.RATE_LIMITED:
            retry = exc.details.get("retry_after")
            if retry is not None:
                headers["Retry-After"] = str(retry)
        return JSONResponse(
            status_code=exc.status,
            content=_body(exc.status, exc.code.value, exc.message, exc.details),
            headers=headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = {"errors": exc.errors()[:20]}
        return JSONResponse(
            status_code=400,
            content=_body(400, ErrorCode.VALIDATION_ERROR.value, "Некорректный запрос", details),
        )
