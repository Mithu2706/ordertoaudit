from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.models.enums import UnitDimension
from app.schemas.common import Email, Gstin, Name, OutSchema, Phone, PositiveFactor, Schema, StateCode


class StateOut(OutSchema):
    code: str
    name: str
    is_union_territory: bool


class UnitOut(OutSchema):
    id: int
    code: str
    name: str
    dimension: UnitDimension


class UnitConversionCreate(Schema):
    from_unit_code: str = Field(min_length=1, max_length=10)
    to_unit_code: str = Field(min_length=1, max_length=10)
    factor: PositiveFactor  # 1 from_unit = factor x to_unit
    item_id: int | None = None  # None = applies to all items


class UnitConversionOut(OutSchema):
    id: int
    from_unit_code: str
    to_unit_code: str
    factor: Decimal
    item_id: int | None


class CompanyProfileUpdate(Schema):
    legal_name: Name | None = None
    trade_name: Name | None = None
    gstin: Gstin | None = None
    state_code: StateCode | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)
    phone: Phone | None = None
    email: Email | None = None


class CompanyProfileOut(OutSchema):
    legal_name: str
    trade_name: str | None
    gstin: str
    state_code: str
    address: str
    phone: str | None
    email: str | None
    fy_start_month: int


class AppSettingOut(OutSchema):
    key: str
    value: str
    description: str | None
    updated_at: datetime


class AppSettingUpdate(Schema):
    value: str = Field(min_length=1, max_length=255)


class AuditLogOut(OutSchema):
    id: int
    occurred_at: datetime
    user_id: int | None
    action: str
    entity_type: str
    entity_id: str
    summary: str | None
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    reason: str | None
    ip_address: str | None
