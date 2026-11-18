"""States, units, unit conversions, company profile and configurable settings."""
from collections.abc import Callable
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session, aliased

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import AppSetting, CompanyProfile, Item, State, Unit, UnitConversion, User
from app.schemas.reference import CompanyProfileUpdate, UnitConversionCreate
from app.services import audit
from app.services.common import apply_changes, ensure_gstin, ensure_state


def list_states(db: Session) -> list[State]:
    return list(db.scalars(select(State).order_by(State.name)))


def list_units(db: Session) -> list[Unit]:
    return list(db.scalars(select(Unit).order_by(Unit.dimension, Unit.code)))


def _unit(db: Session, code: str, field: str) -> Unit:
    unit = db.scalars(select(Unit).where(Unit.code == code.strip().upper())).first()
    if unit is None:
        raise BusinessRuleError(f"Unknown unit '{code}'", {"field": field})
    return unit


# ---- unit conversions -------------------------------------------------------------
def list_conversions(db: Session, item_id: int | None = None) -> list[tuple[UnitConversion, str, str]]:
    fu, tu = aliased(Unit), aliased(Unit)
    stmt = (
        select(UnitConversion, fu.code, tu.code)
        .join(fu, fu.id == UnitConversion.from_unit_id)
        .join(tu, tu.id == UnitConversion.to_unit_id)
        .order_by(UnitConversion.item_id.nulls_first(), fu.code)
    )
    if item_id is not None:
        stmt = stmt.where(or_(UnitConversion.item_id.is_(None), UnitConversion.item_id == item_id))
    return [tuple(r) for r in db.execute(stmt)]


def create_conversion(db: Session, data: UnitConversionCreate, actor: User, ip: str | None = None) -> UnitConversion:
    src = _unit(db, data.from_unit_code, "from_unit_code")
    dst = _unit(db, data.to_unit_code, "to_unit_code")
    if src.id == dst.id:
        raise BusinessRuleError("From and to units must differ")
    if data.item_id is not None and db.get(Item, data.item_id) is None:
        raise BusinessRuleError(f"Item {data.item_id} not found", {"field": "item_id"})
    # kg <-> L only makes sense for a specific item (density); never globally.
    if src.dimension != dst.dimension and data.item_id is None:
        raise BusinessRuleError(
            f"Cannot convert {src.dimension.value} to {dst.dimension.value} globally; give an item_id"
        )
    item_match = UnitConversion.item_id.is_(None) if data.item_id is None else UnitConversion.item_id == data.item_id
    # Either direction already defined -> refuse (the converter derives the inverse).
    existing = db.scalars(
        select(UnitConversion).where(
            item_match,
            or_(
                and_(UnitConversion.from_unit_id == src.id, UnitConversion.to_unit_id == dst.id),
                and_(UnitConversion.from_unit_id == dst.id, UnitConversion.to_unit_id == src.id),
            ),
        )
    ).first()
    if existing:
        raise ConflictError(f"A conversion between {src.code} and {dst.code} already exists for this scope")
    conv = UnitConversion(from_unit_id=src.id, to_unit_id=dst.id, factor=data.factor, item_id=data.item_id)
    db.add(conv)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="unit_conversion", entity_id=conv.id,
                 after=audit.snapshot(conv), summary=f"1 {src.code} = {data.factor} {dst.code}", ip=ip)
    return conv


# ---- company profile --------------------------------------------------------------
def get_company(db: Session) -> CompanyProfile:
    company = db.get(CompanyProfile, 1)
    if company is None:
        raise NotFoundError("Company profile not configured; run the seed script")
    return company


def update_company(db: Session, data: CompanyProfileUpdate, actor: User, ip: str | None = None) -> CompanyProfile:
    company = get_company(db)
    before = audit.snapshot(company)
    apply_changes(company, data.model_dump(exclude_unset=True), {"legal_name", "gstin", "state_code", "address"})
    ensure_state(db, company.state_code)
    ensure_gstin(company.gstin, company.state_code)
    db.flush()
    audit.record_update(db, user_id=actor.id, entity_type="company_profile", entity_id=1,
                        before=before, after=audit.snapshot(company), ip=ip)
    return company


# ---- settings ---------------------------------------------------------------------
def _decimal_between(lo: str, hi: str) -> Callable[[str], str]:
    def check(raw: str) -> str:
        try:
            value = Decimal(raw)
        except InvalidOperation:
            raise BusinessRuleError(f"'{raw}' is not a number") from None
        if not (Decimal(lo) <= value <= Decimal(hi)):
            raise BusinessRuleError(f"Value must be between {lo} and {hi}")
        return str(value)

    return check


def _ageing_buckets(raw: str) -> str:
    try:
        days = [int(p) for p in raw.split(",")]
    except ValueError:
        raise BusinessRuleError("Ageing buckets must be comma-separated whole days, e.g. 30,60,90") from None
    if not days or days != sorted(set(days)) or days[0] <= 0:
        raise BusinessRuleError("Ageing buckets must be positive and strictly increasing")
    return ",".join(map(str, days))


# key -> (default, description, validator)
SETTINGS_SPEC: dict[str, tuple[str, str, Callable[[str], str]]] = {
    "variance_tolerance_pct": ("3.00", "Production variance alert tolerance (%)", _decimal_between("0", "100")),
    "default_gst_rate": ("5.00", "Default GST rate for new products (%)", _decimal_between("0", "28")),
    "receivable_ageing_buckets": ("30,60,90", "Outstanding ageing bucket boundaries (days)", _ageing_buckets),
}


def list_settings(db: Session) -> list[AppSetting]:
    return list(db.scalars(select(AppSetting).order_by(AppSetting.key)))


def get_setting(db: Session, key: str) -> str:
    row = db.get(AppSetting, key)
    return row.value if row else SETTINGS_SPEC[key][0]


def update_setting(db: Session, key: str, value: str, actor: User, ip: str | None = None) -> AppSetting:
    if key not in SETTINGS_SPEC:
        raise NotFoundError(f"Unknown setting '{key}'")
    normalised = SETTINGS_SPEC[key][2](value.strip())
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=SETTINGS_SPEC[key][0], description=SETTINGS_SPEC[key][1])
        db.add(row)
    old = row.value
    row.value = normalised
    row.updated_by = actor.id
    db.flush()
    if old != normalised:
        audit.record(db, user_id=actor.id, action="UPDATE", entity_type="app_setting", entity_id=key,
                     before={"value": old}, after={"value": normalised}, ip=ip)
    db.refresh(row)
    return row
