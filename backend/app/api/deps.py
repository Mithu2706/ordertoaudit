"""Shared FastAPI dependencies: DB session, current user, role guards.

Permissions are enforced HERE (server side). The frontend hiding a button is
cosmetic; every write endpoint declares which roles may call it.
"""
from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import AuthenticationError, PermissionDeniedError
from app.core.security import decode_access_token
from app.models import User
from app.models.enums import RoleCode

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(db: DbSession, token: Annotated[str | None, Depends(oauth2_scheme)]) -> User:
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
