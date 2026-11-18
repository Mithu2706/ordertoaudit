"""Domain exceptions raised by services and mapped to HTTP responses in one place.

Services never import FastAPI; they raise these, and app.main converts them.
Response body: {"error": {"code": "...", "message": "...", "details": {...}}}
"""
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError


class DomainError(Exception):
    status_code = 400
    code = "domain_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(DomainError):
    status_code = 404
    code = "not_found"


class ConflictError(DomainError):
    status_code = 409
    code = "conflict"


class BusinessRuleError(DomainError):
    """Valid input that breaks a business rule (e.g. insufficient stock)."""

    status_code = 422
    code = "business_rule_violation"


class AuthenticationError(DomainError):
    status_code = 401
    code = "not_authenticated"


class PermissionDeniedError(DomainError):
    status_code = 403
    code = "permission_denied"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def _domain(_req: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if isinstance(exc, AuthenticationError) else None
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            _body("validation_error", "Some fields are invalid", jsonable_encoder({"errors": errors})),
            status_code=422,
        )

    @app.exception_handler(IntegrityError)
    async def _integrity(_req: Request, exc: IntegrityError) -> JSONResponse:
        # Safety net: services pre-check uniqueness, but the DB constraint is authoritative.
        return JSONResponse(
            _body("integrity_error", "The change conflicts with existing data or a database rule."),
            status_code=409,
        )
