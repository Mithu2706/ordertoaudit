from datetime import datetime

from pydantic import Field

from app.models import User
from app.models.enums import RoleCode
from app.schemas.common import Email, Name, OutSchema, Phone, Schema

Password = Field(min_length=8, max_length=128)


class UserCreate(Schema):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.]+$")
    full_name: Name
    email: Email | None = None
    phone: Phone | None = None
    password: str = Password
    role: RoleCode


class UserUpdate(Schema):
    full_name: Name | None = None
    email: Email | None = None
    phone: Phone | None = None
    role: RoleCode | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserOut(OutSchema):
    id: int
    username: str
    full_name: str
    email: str | None
    phone: str | None
    role: RoleCode
    is_active: bool
    last_login_at: datetime | None

    @classmethod
    def of(cls, u: User) -> "UserOut":
        return cls(
            id=u.id, username=u.username, full_name=u.full_name, email=u.email, phone=u.phone,
            role=u.role.code, is_active=u.is_active, last_login_at=u.last_login_at,
        )


class TokenOut(OutSchema):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserOut
