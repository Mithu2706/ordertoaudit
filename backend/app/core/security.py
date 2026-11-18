"""Password hashing (bcrypt) and JWT access tokens (PyJWT, HS256)."""
from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(plain: str) -> str:
    rounds = get_settings().bcrypt_rounds
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:  # malformed hash in DB
        return False


def _secret() -> str:
    secret = get_settings().jwt_secret_key
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not configured")
    return secret


def create_access_token(user_id: int, role: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_access_token_expire_minutes
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,  # informational for the UI; the server always re-reads the role from the DB
        "iat": now,
        "exp": now + timedelta(minutes=minutes),
    }
    return jwt.encode(payload, _secret(), algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Raises jwt.PyJWTError on invalid/expired tokens. Algorithm is pinned (no 'none')."""
    settings = get_settings()
    return jwt.decode(token, _secret(), algorithms=[settings.jwt_algorithm], options={"require": ["sub", "exp"]})
