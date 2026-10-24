"""Contract error format: {"error": {"code", "message", "details"}} for every non-2xx response."""
from __future__ import annotations

import logging
from typing import Any

from starlette.responses import JSONResponse

log = logging.getLogger("sunwai.errors")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}

    def to_response(self) -> JSONResponse:
        return error_response(self.status, self.code, self.message, self.details)


def error_response(status: int, code: str, message: str, details: dict[str, Any] | None = None,
                   headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}},
                        status_code=status, headers=headers)


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found.")


def illegal(message: str, **details: Any) -> ApiError:
    return ApiError(409, "ILLEGAL_TRANSITION", message, details)


def bad_request(message: str, **details: Any) -> ApiError:
    return ApiError(400, "BAD_REQUEST", message, details)


def validation_error(fields: list[dict[str, Any]], message: str = "Request validation failed.") -> ApiError:
    return ApiError(422, "VALIDATION_ERROR", message, {"fields": fields})


def pydantic_fields(exc: Any) -> list[dict[str, Any]]:
    out = []
    for e in exc.errors():
        out.append({"field": ".".join(str(p) for p in e.get("loc", ())), "message": e.get("msg", "invalid")})
    return out
