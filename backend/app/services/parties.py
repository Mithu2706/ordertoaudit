"""Customer and supplier masters.

Masters are never hard-deleted (invoices and ledgers reference them); they are deactivated.
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Customer, Role, Supplier, User
from app.models.enums import RoleCode
from app.schemas.parties import CustomerCreate, CustomerUpdate, SupplierCreate, SupplierUpdate
from app.services import audit
from app.services.common import (
    apply_changes,
    ensure_gstin,
    ensure_state,
    ensure_unique,
    get_or_404,
    paginate,
)

_CUSTOMER_REQUIRED = {"name", "customer_type", "state_code", "address", "credit_limit", "credit_days", "is_active"}
_SUPPLIER_REQUIRED = {"name", "state_code", "is_active"}


def _ensure_salesman(db: Session, user_id: int | None) -> None:
    if user_id is None:
        return
    user = db.get(User, user_id)
    if user is None or user.role.code != RoleCode.SALESMAN or not user.is_active:
        raise BusinessRuleError("Assigned salesman must be an active user with the SALESMAN role",
                                {"field": "assigned_salesman_id"})


# ---- customers --------------------------------------------------------------
def _customer_scope(stmt, actor: User):
    """Salesmen only ever see customers assigned to them."""
    if actor.role.code == RoleCode.SALESMAN:
        return stmt.where(Customer.assigned_salesman_id == actor.id)
    return stmt


def list_customers(db: Session, actor: User, q: str | None, active: bool | None, limit: int, offset: int):
    stmt = _customer_scope(select(Customer), actor).order_by(Customer.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Customer.name.ilike(like), Customer.code.ilike(like), Customer.city.ilike(like)))
    if active is not None:
        stmt = stmt.where(Customer.is_active == active)
    return paginate(db, stmt, limit, offset)


def get_customer(db: Session, customer_id: int, actor: User) -> Customer:
    cust = db.scalars(_customer_scope(select(Customer).where(Customer.id == customer_id), actor)).first()
    if cust is None:  # same message whether missing or not assigned: no information leak
        raise NotFoundError(f"Customer {customer_id} not found")
    return cust


def create_customer(db: Session, data: CustomerCreate, actor: User, ip: str | None = None) -> Customer:
    ensure_unique(db, Customer.code, data.code, "Customer code")
    ensure_state(db, data.state_code)
    ensure_gstin(data.gstin, data.state_code)
    _ensure_salesman(db, data.assigned_salesman_id)
    cust = Customer(**data.model_dump(), is_active=True)
    db.add(cust)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="customer", entity_id=cust.id,
                 after=audit.snapshot(cust), summary=f"Customer {cust.code} created", ip=ip)
    return cust


def update_customer(db: Session, customer_id: int, data: CustomerUpdate, actor: User, ip: str | None = None) -> Customer:
    cust = get_or_404(db, Customer, customer_id, "Customer")
    changes = data.model_dump(exclude_unset=True)
    before = audit.snapshot(cust)
    apply_changes(cust, changes, _CUSTOMER_REQUIRED)
    # Validate the combination that results from the patch (e.g. new state + old GSTIN).
    ensure_state(db, cust.state_code)
    ensure_gstin(cust.gstin, cust.state_code)
    if "assigned_salesman_id" in changes:
        _ensure_salesman(db, cust.assigned_salesman_id)
    db.flush()
    audit.record_update(db, user_id=actor.id, entity_type="customer", entity_id=cust.id,
                        before=before, after=audit.snapshot(cust), ip=ip)
    return cust


# ---- suppliers ----------------------------------------------------------------
def list_suppliers(db: Session, q: str | None, active: bool | None, limit: int, offset: int):
    stmt = select(Supplier).order_by(Supplier.name)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Supplier.name.ilike(like), Supplier.code.ilike(like)))
    if active is not None:
        stmt = stmt.where(Supplier.is_active == active)
    return paginate(db, stmt, limit, offset)


def create_supplier(db: Session, data: SupplierCreate, actor: User, ip: str | None = None) -> Supplier:
    ensure_unique(db, Supplier.code, data.code, "Supplier code")
    ensure_state(db, data.state_code)
    ensure_gstin(data.gstin, data.state_code)
    sup = Supplier(**data.model_dump(), is_active=True)
    db.add(sup)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="supplier", entity_id=sup.id,
                 after=audit.snapshot(sup), summary=f"Supplier {sup.code} created", ip=ip)
    return sup


def update_supplier(db: Session, supplier_id: int, data: SupplierUpdate, actor: User, ip: str | None = None) -> Supplier:
    sup = get_or_404(db, Supplier, supplier_id, "Supplier")
    before = audit.snapshot(sup)
    apply_changes(sup, data.model_dump(exclude_unset=True), _SUPPLIER_REQUIRED)
    ensure_state(db, sup.state_code)
    ensure_gstin(sup.gstin, sup.state_code)
    db.flush()
    audit.record_update(db, user_id=actor.id, entity_type="supplier", entity_id=sup.id,
                        before=before, after=audit.snapshot(sup), ip=ip)
    return sup


def list_salesmen(db: Session) -> list[User]:
    return list(db.scalars(select(User).join(Role).where(Role.code == RoleCode.SALESMAN, User.is_active)
                           .order_by(User.full_name)))
