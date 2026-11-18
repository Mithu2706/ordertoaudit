from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.users import TokenOut, UserOut
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(db: DbSession, request: Request, form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenOut:
    """OAuth2 password flow (form fields `username`, `password`) — also works from Swagger's Authorize button."""
    user = user_service.authenticate(db, form.username, form.password, ip=client_ip(request))
    minutes = get_settings().jwt_access_token_expire_minutes
    return TokenOut(
        access_token=create_access_token(user.id, user.role.code.value),
        expires_in_minutes=minutes,
        user=UserOut.of(user),
    )


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
