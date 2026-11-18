"""Idempotent reference data + demo users. Safe to run repeatedly.

Business master data for the benchmark (items, BOM, customers, opening stock) is
loaded by the benchmark seed in a later phase, because opening stock must go
through the stock ledger.
"""
import os
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.gstin import gstin_check_char
from app.core.security import hash_password
from app.models import AppSetting, CompanyProfile, Role, State, Unit, UnitConversion, User
from app.models.enums import RoleCode, UnitDimension
from app.services.reference import SETTINGS_SPEC

ROLES = [
    (RoleCode.SALESMAN, "Salesman", "Creates and tracks customer orders"),
    (RoleCode.ADMIN, "Admin", "Approves orders, invoices, dispatch, payments, masters"),
    (RoleCode.PRODUCTION, "Production Supervisor", "Receipts, production runs, variance"),
    (RoleCode.OWNER, "Owner", "Business dashboard and oversight"),
    (RoleCode.AUDITOR, "Accountant / Auditor", "Read-only financial and inventory reports"),
]

# GST state codes. is_union_territory marks UTs without a legislature (UTGST applies there).
STATES = [
    ("01", "Jammu and Kashmir", False), ("02", "Himachal Pradesh", False), ("03", "Punjab", False),
    ("04", "Chandigarh", True), ("05", "Uttarakhand", False), ("06", "Haryana", False),
    ("07", "Delhi", False), ("08", "Rajasthan", False), ("09", "Uttar Pradesh", False),
    ("10", "Bihar", False), ("11", "Sikkim", False), ("12", "Arunachal Pradesh", False),
    ("13", "Nagaland", False), ("14", "Manipur", False), ("15", "Mizoram", False),
    ("16", "Tripura", False), ("17", "Meghalaya", False), ("18", "Assam", False),
    ("19", "West Bengal", False), ("20", "Jharkhand", False), ("21", "Odisha", False),
    ("22", "Chhattisgarh", False), ("23", "Madhya Pradesh", False), ("24", "Gujarat", False),
    ("26", "Dadra and Nagar Haveli and Daman and Diu", True), ("27", "Maharashtra", False),
    ("29", "Karnataka", False), ("30", "Goa", False), ("31", "Lakshadweep", True),
    ("32", "Kerala", False), ("33", "Tamil Nadu", False), ("34", "Puducherry", False),
    ("35", "Andaman and Nicobar Islands", True), ("36", "Telangana", False),
    ("37", "Andhra Pradesh", False), ("38", "Ladakh", True), ("97", "Other Territory", True),
]

UNITS = [
    ("KG", "Kilogram", UnitDimension.MASS), ("G", "Gram", UnitDimension.MASS),
    ("L", "Litre", UnitDimension.VOLUME), ("ML", "Millilitre", UnitDimension.VOLUME),
    ("PCS", "Piece", UnitDimension.COUNT), ("PKT", "Packet", UnitDimension.COUNT),
    ("CTN", "Carton", UnitDimension.COUNT),
]
GLOBAL_CONVERSIONS = [("KG", "G", Decimal("1000")), ("L", "ML", Decimal("1000"))]


def _with_check(first14: str) -> str:
    return first14 + gstin_check_char(first14)


# Fictional manufacturer used throughout the exercise.
COMPANY = dict(
    legal_name="Sri Annapoorna Snacks Private Limited",
    trade_name="Annapoorna Snacks",
    gstin=_with_check("33AAKCA1234F1Z"),
    state_code="33",
    address="12 SIDCO Industrial Estate, Kurichi, Coimbatore, Tamil Nadu 641021",
    phone="0422-2345678",
    email="accounts@annapoorna-snacks.example",
    fy_start_month=4,
)

# Demo accounts (one per role, two salesmen for the benchmark). Demo-only credentials:
# the password comes from SEED_DEMO_PASSWORD and is documented in the README.
DEMO_USERS = [
    ("owner", "Lakshmi Narayanan (Owner)", RoleCode.OWNER),
    ("admin", "Priya Raman (Admin)", RoleCode.ADMIN),
    ("production", "Murugan S (Production)", RoleCode.PRODUCTION),
    ("auditor", "Kavitha R (Accountant/Auditor)", RoleCode.AUDITOR),
    ("salesman_a", "Arun Kumar (Salesman A)", RoleCode.SALESMAN),
    ("salesman_b", "Bala Subramanian (Salesman B)", RoleCode.SALESMAN),
]
DEFAULT_DEMO_PASSWORD = "Demo@1234"


def seed_reference(db: Session) -> None:
    for code, name, desc in ROLES:
        if db.scalars(select(Role).where(Role.code == code)).first() is None:
            db.add(Role(code=code, name=name, description=desc))
    for code, name, is_ut in STATES:
        if db.get(State, code) is None:
            db.add(State(code=code, name=name, is_union_territory=is_ut))
    for code, name, dim in UNITS:
        if db.scalars(select(Unit).where(Unit.code == code)).first() is None:
            db.add(Unit(code=code, name=name, dimension=dim))
    db.flush()

    units = {u.code: u.id for u in db.scalars(select(Unit))}
    for src, dst, factor in GLOBAL_CONVERSIONS:
        exists_ = db.scalars(select(UnitConversion).where(
            UnitConversion.from_unit_id == units[src], UnitConversion.to_unit_id == units[dst],
            UnitConversion.item_id.is_(None))).first()
        if exists_ is None:
            db.add(UnitConversion(from_unit_id=units[src], to_unit_id=units[dst], factor=factor))

    if db.get(CompanyProfile, 1) is None:
        db.add(CompanyProfile(id=1, **COMPANY))
    for key, (default, description, _validator) in SETTINGS_SPEC.items():
        if db.get(AppSetting, key) is None:
            db.add(AppSetting(key=key, value=default, description=description))
    db.flush()


def seed_demo_users(db: Session, password: str | None = None) -> list[str]:
    password = password or os.environ.get("SEED_DEMO_PASSWORD") or DEFAULT_DEMO_PASSWORD
    roles = {r.code: r.id for r in db.scalars(select(Role))}
    created = []
    hashed = None
    for username, full_name, role in DEMO_USERS:
        if db.scalars(select(User).where(User.username == username)).first() is None:
            hashed = hashed or hash_password(password)
            db.add(User(username=username, full_name=full_name, password_hash=hashed,
                        role_id=roles[role], is_active=True))
            created.append(username)
    db.flush()
    return created
