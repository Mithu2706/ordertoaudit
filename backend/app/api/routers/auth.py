import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CSRF_COOKIE, SESSION_COOKIE, CurrentUser, DbSession, client_ip
from app.core.config import get_settings
from app.core.security import create_access_token
from app.schemas.users import TokenOut, UserOut
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])


def _secure(request: Request) -> bool:
    setting = get_settings().cookie_secure.lower()
    return request.url.scheme == "https" if setting == "auto" else setting == "true"


@router.post("/login", response_model=TokenOut)
def login(db: DbSession, request: Request, response: Response,
          form: Annotated[OAuth2PasswordRequestForm, Depends()]) -> TokenOut:
    """OAuth2 password flow (form fields `username`, `password`).

    Browser app: the session is set as an httpOnly cookie (plus a readable CSRF cookie) and the
    app never stores the token. API clients and Swagger's Authorize button use the returned
    `access_token` as a bearer token instead."""
    user = user_service.authenticate(db, form.username, form.password, ip=client_ip(request))
    minutes = get_settings().jwt_access_token_expire_minutes
    token = create_access_token(user.id, user.role.code.value)
    secure = _secure(request)
    response.set_cookie(SESSION_COOKIE, token, max_age=minutes * 60, path="/api", httponly=True,
                        secure=secure, samesite="strict")
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), max_age=minutes * 60, path="/", httponly=False,
                        secure=secure, samesite="strict")
    return TokenOut(access_token=token, expires_in_minutes=minutes, user=UserOut.of(user))


@router.post("/logout", status_code=204)
def logout(response: Response) -> Response:
    """End the browser session (clears both cookies). Bearer tokens simply expire."""
    response.status_code = 204
    response.delete_cookie(SESSION_COOKIE, path="/api", samesite="strict")
    response.delete_cookie(CSRF_COOKIE, path="/", samesite="strict")
    return response


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.of(user)
