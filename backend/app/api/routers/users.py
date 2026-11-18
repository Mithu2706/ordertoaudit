from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import USER_MANAGERS, DbSession, client_ip, require_roles
from app.api.routers._params import Listing
from app.models import User
from app.models.enums import RoleCode
from app.schemas.common import Page
from app.schemas.users import UserCreate, UserOut, UserUpdate
from app.services import parties as party_service
from app.services import users as user_service

router = APIRouter(prefix="/users", tags=["users"])
Manager = Annotated[User, Depends(require_roles(*USER_MANAGERS))]


@router.get("", response_model=Page[UserOut])
def list_users(db: DbSession, _: Manager, params: Listing, role: Annotated[RoleCode | None, Query()] = None):
    rows, total = user_service.list_users(db, params.q, role, params.limit, params.offset)
    return Page(items=[UserOut.of(u) for u in rows], total=total, limit=params.limit, offset=params.offset)


@router.get("/salesmen", response_model=list[UserOut])
def list_salesmen(db: DbSession, _: Annotated[User, Depends(require_roles(RoleCode.ADMIN, RoleCode.OWNER, RoleCode.AUDITOR))]):
    """Active salesmen, for customer assignment drop-downs."""
    return [UserOut.of(u) for u in party_service.list_salesmen(db)]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: DbSession, _: Manager):
    return UserOut.of(user_service.require_user(db, user_id))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(data: UserCreate, db: DbSession, actor: Manager, request: Request):
    return UserOut.of(user_service.create_user(db, data, actor, client_ip(request)))


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, data: UserUpdate, db: DbSession, actor: Manager, request: Request):
    return UserOut.of(user_service.update_user(db, user_id, data, actor, client_ip(request)))
