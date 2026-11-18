from decimal import Decimal

from pydantic import Field

from app.models.enums import CustomerType
from app.schemas.common import Code, Email, Gstin, MoneyIn, Name, OutSchema, Phone, Pincode, Schema, StateCode

Address = Field(min_length=1, max_length=500)


class CustomerCreate(Schema):
    code: Code
    name: Name
    customer_type: CustomerType
    gstin: Gstin | None = None
    state_code: StateCode
    address: str = Address
    city: str | None = Field(default=None, max_length=64)
    pincode: Pincode | None = None
    phone: Phone | None = None
    email: Email | None = None
    credit_limit: MoneyIn = Decimal("0.00")
    credit_days: int = Field(default=30, ge=0, le=365)
    assigned_salesman_id: int | None = None


class CustomerUpdate(Schema):
    name: Name | None = None
    customer_type: CustomerType | None = None
    gstin: Gstin | None = None
    state_code: StateCode | None = None
    address: str | None = Field(default=None, min_length=1, max_length=500)
    city: str | None = Field(default=None, max_length=64)
    pincode: Pincode | None = None
    phone: Phone | None = None
    email: Email | None = None
    credit_limit: MoneyIn | None = None
    credit_days: int | None = Field(default=None, ge=0, le=365)
    assigned_salesman_id: int | None = None
    is_active: bool | None = None


class CustomerOut(OutSchema):
    id: int
    code: str
    name: str
    customer_type: CustomerType
    gstin: str | None
    state_code: str
    address: str
    city: str | None
    pincode: str | None
    phone: str | None
    email: str | None
    credit_limit: Decimal
    credit_days: int
    assigned_salesman_id: int | None
    is_active: bool


class SupplierCreate(Schema):
    code: Code
    name: Name
    gstin: Gstin | None = None
    state_code: StateCode
    address: str | None = Field(default=None, max_length=500)
    phone: Phone | None = None
    email: Email | None = None


class SupplierUpdate(Schema):
    name: Name | None = None
    gstin: Gstin | None = None
    state_code: StateCode | None = None
    address: str | None = Field(default=None, max_length=500)
    phone: Phone | None = None
    email: Email | None = None
    is_active: bool | None = None


class SupplierOut(OutSchema):
    id: int
    code: str
    name: str
    gstin: str | None
    state_code: str
    address: str | None
    phone: str | None
    email: str | None
    is_active: bool
