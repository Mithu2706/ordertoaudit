from datetime import date, datetime, time, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select

from app.api.deps import (
    ALL_ROLES,
    AUDIT_READERS,
    MATERIAL_WRITERS,
    SETTINGS_WRITERS,
    CurrentUser,
    DbSession,
    client_ip,
    require_roles,
)
from app.models import AuditLog, User
from app.models.enums import RoleCode
from app.schemas.common import Page
from app.schemas.reference import (
    AppSettingOut,
    AppSettingUpdate,
    AuditLogOut,
    CompanyProfileOut,
    CompanyProfileUpdate,
    StateOut,
    UnitConversionCreate,
    UnitConversionOut,
    UnitOut,
)
from app.services import reference as svc
from app.services.common import paginate

router = APIRouter(tags=["reference"])
AnyUser = Annotated[User, Depends(require_roles(*ALL_ROLES))]
SettingsWriter = Annotated[User, Depends(require_roles(*SETTINGS_WRITERS))]
StaffReader = Annotated[User, Depends(require_roles(RoleCode.ADMIN, RoleCode.PRODUCTION, RoleCode.OWNER, RoleCode.AUDITOR))]


@router.get("/states", response_model=list[StateOut])
def states(db: DbSession, _: CurrentUser):
    return svc.list_states(db)


@router.get("/units", response_model=list[UnitOut])
def units(db: DbSession, _: CurrentUser):
    return svc.list_units(db)


@router.get("/unit-conversions", response_model=list[UnitConversionOut])
def conversions(db: DbSession, _: CurrentUser, item_id: Annotated[int | None, Query()] = None):
    return [
        UnitConversionOut(id=c.id, from_unit_code=f, to_unit_code=t, factor=c.factor, item_id=c.item_id)
        for c, f, t in svc.list_conversions(db, item_id)
    ]


@router.post("/unit-conversions", response_model=UnitConversionOut, status_code=status.HTTP_201_CREATED)
def create_conversion(data: UnitConversionCreate, db: DbSession, request: Request,
                      actor: Annotated[User, Depends(require_roles(*MATERIAL_WRITERS))]):
    c = svc.create_conversion(db, data, actor, client_ip(request))
    return UnitConversionOut(id=c.id, from_unit_code=data.from_unit_code.upper(),
                             to_unit_code=data.to_unit_code.upper(), factor=c.factor, item_id=c.item_id)


@router.get("/company", response_model=CompanyProfileOut)
def company(db: DbSession, _: AnyUser):
    return svc.get_company(db)


@router.patch("/company", response_model=CompanyProfileOut)
def update_company(data: CompanyProfileUpdate, db: DbSession, actor: SettingsWriter, request: Request):
    return svc.update_company(db, data, actor, client_ip(request))


@router.get("/settings", response_model=list[AppSettingOut])
def settings(db: DbSession, _: StaffReader):
    return svc.list_settings(db)


@router.put("/settings/{key}", response_model=AppSettingOut)
def update_setting(key: str, data: AppSettingUpdate, db: DbSession, actor: SettingsWriter, request: Request):
    return svc.update_setting(db, key, data.value, actor, client_ip(request))


@router.get("/audit-logs", response_model=Page[AuditLogOut])
def audit_logs(
    db: DbSession,
    _: Annotated[User, Depends(require_roles(*AUDIT_READERS))],
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    user_id: Annotated[int | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=32)] = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    stmt = select(AuditLog).order_by(AuditLog.id.desc())
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        stmt = stmt.where(AuditLog.action == action.upper())
    if date_from:
        stmt = stmt.where(AuditLog.occurred_at >= datetime.combine(date_from, time.min))
    if date_to:
        stmt = stmt.where(AuditLog.occurred_at < datetime.combine(date_to + timedelta(days=1), time.min))
    rows, total = paginate(db, stmt, limit, offset)
    ids = {r.user_id for r in rows if r.user_id is not None}
    names = dict(db.execute(select(User.id, User.username).where(User.id.in_(ids))).all()) if ids else {}
    items = [AuditLogOut.model_validate(r).model_copy(update={"username": names.get(r.user_id)}) for r in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)
