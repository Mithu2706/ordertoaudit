"""Shared FastAPI dependencies: DB session, current user, role guards.

Permissions are enforced HERE (server side). The frontend hiding a button is
cosmetic; every write endpoint declares which roles may call it.
"""
from collections.abc import Callable
from typing import Annotated

import hmac

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthenticationError, CsrfError, PermissionDeniedError
from app.core.security import decode_access_token
from app.models import User
from app.models.enums import RoleCode

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


SESSION_COOKIE = "ota_session"  # httpOnly JWT for the browser app (scripts can't read it)
CSRF_COOKIE = "ota_csrf"  # readable token the app echoes in X-CSRF-Token (double-submit)
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _token_from_request(request: Request, bearer: str | None) -> str | None:
    """Bearer header (API clients, Swagger) or the session cookie (browser app).

    A cookie is sent by the browser automatically, so a cookie-authenticated write must also carry
    the CSRF token from the readable cookie in a header, which another site cannot do. Bearer
    requests need no CSRF check: browsers never attach that header on their own."""
    if bearer:
        return bearer
    token = request.cookies.get(SESSION_COOKIE)
    if token and request.method not in SAFE_METHODS:
        expected = request.cookies.get(CSRF_COOKIE) or ""
        sent = request.headers.get(CSRF_HEADER) or ""
        if not expected or not hmac.compare_digest(expected, sent):
            raise CsrfError("Missing or invalid CSRF token; reload the page and try again")
    return token


def get_current_user(db: DbSession, request: Request,
                     bearer: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
    token = _token_from_request(request, bearer)
    if not token:
        raise AuthenticationError("Not authenticated")
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise AuthenticationError("Invalid or expired token") from None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("User is inactive or no longer exists")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: RoleCode) -> Callable[..., User]:
    """Dependency factory: `user: User = Depends(require_roles(RoleCode.ADMIN))`."""
    allowed = frozenset(roles)

    def _guard(user: CurrentUser) -> User:
        if user.role.code not in allowed:
            raise PermissionDeniedError(
                "Your role is not allowed to perform this action",
                {"role": user.role.code.value, "allowed": sorted(r.value for r in allowed)},
            )
        return user

    return _guard


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


# Role groups used across routers — one place to read the permission matrix.
R = RoleCode
ALL_ROLES = (R.SALESMAN, R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR)
MASTER_READERS = (R.ADMIN, R.OWNER, R.AUDITOR)  # read-only oversight + admin
MATERIAL_READERS = (R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR)
MATERIAL_WRITERS = (R.ADMIN, R.PRODUCTION)
SALES_MASTER_WRITERS = (R.ADMIN,)
USER_MANAGERS = (R.ADMIN, R.OWNER)
SETTINGS_WRITERS = (R.ADMIN, R.OWNER)
AUDIT_READERS = (R.ADMIN, R.OWNER, R.AUDITOR)
