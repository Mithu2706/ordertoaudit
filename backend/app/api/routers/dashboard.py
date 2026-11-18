from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_roles
from app.models import User
from app.models.enums import RoleCode
from app.services.dashboard import owner_dashboard

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("")
def dashboard(db: DbSession, _: Annotated[User, Depends(require_roles(RoleCode.OWNER, RoleCode.ADMIN, RoleCode.AUDITOR))]):
    """Business KPIs computed live (no stored or hard-coded metrics)."""
    return owner_dashboard(db)
