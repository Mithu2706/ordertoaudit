"""Sales orders: salesman drafts and submits; admin verifies stock, then approves or rejects.

    DRAFT --submit--> SUBMITTED --approve--> APPROVED --(phase 6: invoice, dispatch)-->
                        |   +--reject--> REJECTED
    DRAFT / SUBMITTED / APPROVED --cancel--> CANCELLED

* Prices come from the product master when the order is created; salesmen cannot set them.
* Approval is the stock commitment: approved quantities are reserved (see availability.py).
  The admin may approve less than ordered or correct a price, with a mandatory reason that
  goes into the audit trail. Approving more than is available is refused, with the shortage.
* Approval checks the order `version` the admin looked at (optimistic locking), so an
  order changed in the meantime cannot be approved blind.
"""
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError, PermissionDeniedError
from app.models import Customer, Item, Product, SalesOrder, SalesOrderItem, User
from app.models.enums import DocumentType, OrderStatus, RoleCode, UnitDimension
from app.schemas.sales import ApproveIn, OrderIn
from app.services import audit, credit, numbering
from app.services.availability import availability, check_order
from app.services.common import paginate
from app.services.inventory import InsufficientStockError, lock_item
from app.services.parties import get_customer


def _scope(stmt, actor: User):
    if actor.role.code == RoleCode.SALESMAN:
        return stmt.where(SalesOrder.salesman_id == actor.id)
    return stmt


def get_order(db: Session, order_id: int, actor: User, lock: bool = False) -> SalesOrder:
    stmt = _scope(select(SalesOrder).where(SalesOrder.id == order_id), actor)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    order = db.scalars(stmt).first()
    if order is None:
        raise NotFoundError(f"Sales order {order_id} not found")
    return order


def _lines_snapshot(order: SalesOrder) -> list[dict]:
    return [{"id": li.id, "product_id": li.product_id, "ordered": str(li.quantity_ordered),
             "approved": None if li.quantity_approved is None else str(li.quantity_approved),
             "unit_price": str(li.unit_price)} for li in order.items]


def _whole_if_counted(item: Item, qty: Decimal, label: str) -> None:
    if item.base_unit.dimension == UnitDimension.COUNT and qty != qty.to_integral_value():
        raise BusinessRuleError(f"{label}: {item.code} is sold in whole {item.base_unit.code}")


def _build_lines(db: Session, order: SalesOrder, data: OrderIn) -> None:
    order.items.clear()
    for n, line in enumerate(data.items, start=1):
        product = db.get(Product, line.product_id)
        if product is None or not product.item.is_active:
            raise BusinessRuleError(f"Line {n}: product {line.product_id} not found or inactive")
        _whole_if_counted(product.item, line.quantity, f"Line {n}")
        order.items.append(SalesOrderItem(
            product_id=product.item_id, quantity_ordered=line.quantity, unit_price=product.selling_price,
            line_amount=dec.money(line.quantity * product.selling_price),
        ))


def _n(value: str) -> str:
    """'120.0000' -> '120' for human-readable messages (details keep full precision)."""
    return f"{Decimal(value).normalize():f}"


def _money(value: Decimal) -> str:
    return f"Rs {value:,.2f}"


def _require_owner_salesman(order: SalesOrder, actor: User) -> None:
    if actor.role.code != RoleCode.SALESMAN or order.salesman_id != actor.id:
        raise PermissionDeniedError("Only the salesman who created the order can change it")


def create_order(db: Session, data: OrderIn, actor: User, ip: str | None = None) -> SalesOrder:
    if actor.role.code != RoleCode.SALESMAN:
        raise PermissionDeniedError("Orders are created by salesmen")
    customer = get_customer(db, data.customer_id, actor)  # 404 unless assigned to this salesman
    if not customer.is_active:
        raise BusinessRuleError("Customer is inactive")
    today = date.today()
    order = SalesOrder(order_no=numbering.next_number(db, DocumentType.SALES_ORDER, today).number,
                       customer_id=customer.id, salesman_id=actor.id, order_date=today,
                       status=OrderStatus.DRAFT, remarks=data.remarks, items=[])
    _build_lines(db, order, data)
    db.add(order)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="sales_order", entity_id=order.id,
                 after={**audit.snapshot(order), "items": _lines_snapshot(order)},
                 summary=f"Order {order.order_no} drafted", ip=ip)
    return order


def update_order(db: Session, order_id: int, data: OrderIn, actor: User, ip: str | None = None) -> SalesOrder:
    order = get_order(db, order_id, actor, lock=True)
    _require_owner_salesman(order, actor)
    if order.status != OrderStatus.DRAFT:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value}; only drafts can be edited")
    if data.customer_id != order.customer_id:
        customer = get_customer(db, data.customer_id, actor)
        order.customer_id = customer.id
    before = _lines_snapshot(order)
    order.remarks = data.remarks
    _build_lines(db, order, data)
    db.flush()
    audit.record(db, user_id=actor.id, action="UPDATE", entity_type="sales_order", entity_id=order.id,
                 before={"items": before}, after={"items": _lines_snapshot(order)}, ip=ip)
    return order


def submit_order(db: Session, order_id: int, actor: User, ip: str | None = None) -> SalesOrder:
    order = get_order(db, order_id, actor, lock=True)
    _require_owner_salesman(order, actor)
    if order.status != OrderStatus.DRAFT:
        raise BusinessRuleError(f"Order {order.order_no} is already {order.status.value}")
    if not db.get(Customer, order.customer_id).is_active:
        raise BusinessRuleError("Customer is inactive")
    order.status = OrderStatus.SUBMITTED
    order.submitted_at = datetime.now(UTC)
    db.flush()
    audit.record(db, user_id=actor.id, action="SUBMIT", entity_type="sales_order", entity_id=order.id,
                 summary=f"Order {order.order_no} submitted for approval", ip=ip)
    return order


def approve_order(db: Session, order_id: int, data: ApproveIn, actor: User, ip: str | None = None) -> SalesOrder:
    order = get_order(db, order_id, actor, lock=True)
    if order.status != OrderStatus.SUBMITTED:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value}; only submitted orders can be approved")
    if data.version != order.version:
        raise ConflictError("The order changed since you opened it; reload and review again",
                            {"current_version": order.version})

    lines = {li.id: li for li in order.items}
    approved = {li.id: li.quantity_ordered for li in order.items}
    prices = {li.id: li.unit_price for li in order.items}
    for change in data.lines:
        line = lines.get(change.order_item_id)
        if line is None:
            raise BusinessRuleError(f"Line {change.order_item_id} does not belong to this order")
        if change.quantity_approved > line.quantity_ordered:
            raise BusinessRuleError(f"Line {line.id}: cannot approve more than ordered ({line.quantity_ordered})")
        approved[line.id] = change.quantity_approved
        if change.unit_price is not None:
            prices[line.id] = change.unit_price
    modified = any(approved[i] != lines[i].quantity_ordered or prices[i] != lines[i].unit_price for i in lines)
    if modified and not data.reason:
        raise BusinessRuleError("A reason is required when changing quantities or prices", {"field": "reason"})
    if all(q == 0 for q in approved.values()):
        raise BusinessRuleError("Approve at least one line, or reject the order")

    # Lock the products (in id order: no deadlocks) so concurrent approvals see each other.
    for pid in sorted({li.product_id for li in order.items}):
        lock_item(db, pid)
    shortages = []
    for check in check_order(db, order, approved):
        item = db.get(Item, check.product_id)
        _whole_if_counted(item, check.requested, f"Line {check.order_item_id}")
        if not check.can_fulfil:
            shortages.append({"order_item_id": check.order_item_id, "product_code": item.code,
                              "requested": str(check.requested), "available": str(check.available),
                              "shortage": str(check.shortage)})
    if shortages:
        first = shortages[0]
        raise InsufficientStockError(
            f"Insufficient stock for {first['product_code']}: requested {_n(first['requested'])}, "
            f"available {_n(first['available'])}, short by {_n(first['shortage'])}. "
            "Approve a smaller quantity or keep the order pending.",
            {"lines": shortages, "shortage": first["shortage"]},
        )

    # Credit control. Lock the customer so two approvals can't both fit under the same limit.
    customer = db.scalars(select(Customer).where(Customer.id == order.customer_id)
                          .with_for_update().execution_options(populate_existing=True)).one()
    credit_pos = credit.position(db, customer, this_order=credit.order_value(db, order, approved, prices),
                                 exclude_order_id=order.id)
    credit_override = None
    if credit_pos.exceeds:
        if not data.credit_override_reason:
            raise credit.CreditLimitError(
                f"Credit limit exceeded for {customer.name}: limit {_money(credit_pos.limit)}, exposure with this "
                f"order {_money(credit_pos.exposure)} (over by {_money(credit_pos.excess)}). Reduce the order, "
                "collect payment first, or approve with a credit-override reason.",
                {**credit_pos.details(), "field": "credit_override_reason"},
            )
        credit_override = {**credit_pos.details(), "reason": data.credit_override_reason}

    before = _lines_snapshot(order)
    for li in order.items:
        li.quantity_approved = approved[li.id]
        li.unit_price = prices[li.id]
        li.line_amount = dec.money(approved[li.id] * prices[li.id])
    order.status = OrderStatus.APPROVED
    order.reviewed_by = actor.id
    order.reviewed_at = datetime.now(UTC)
    db.flush()
    audit.record(db, user_id=actor.id, action="APPROVE", entity_type="sales_order", entity_id=order.id,
                 before={"items": before},
                 after={"items": _lines_snapshot(order), **({"credit_override": credit_override} if credit_override else {})},
                 reason="; ".join(r for r in (data.reason, credit_override and f"Credit override: {data.credit_override_reason}") if r) or None,
                 summary=f"Order {order.order_no} approved" + (" with changes" if modified else "")
                         + (" over the credit limit" if credit_override else ""), ip=ip)
    return order


def reject_order(db: Session, order_id: int, version: int, reason: str, actor: User, ip: str | None = None) -> SalesOrder:
    order = get_order(db, order_id, actor, lock=True)
    if order.status != OrderStatus.SUBMITTED:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value}; only submitted orders can be rejected")
    if version != order.version:
        raise ConflictError("The order changed since you opened it; reload and review again")
    order.status = OrderStatus.REJECTED
    order.rejection_reason = reason
    order.reviewed_by = actor.id
    order.reviewed_at = datetime.now(UTC)
    db.flush()
    audit.record(db, user_id=actor.id, action="REJECT", entity_type="sales_order", entity_id=order.id,
                 reason=reason, summary=f"Order {order.order_no} rejected", ip=ip)
    return order


def cancel_order(db: Session, order_id: int, reason: str, actor: User, ip: str | None = None) -> SalesOrder:
    order = get_order(db, order_id, actor, lock=True)
    if actor.role.code == RoleCode.SALESMAN:
        allowed = (OrderStatus.DRAFT, OrderStatus.SUBMITTED)
    elif actor.role.code == RoleCode.ADMIN:
        allowed = (OrderStatus.DRAFT, OrderStatus.SUBMITTED, OrderStatus.APPROVED)  # releases the reservation
    else:
        raise PermissionDeniedError("Your role cannot cancel orders")
    if order.status not in allowed:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value} and cannot be cancelled by you")
    previous = order.status
    order.status = OrderStatus.CANCELLED
    db.flush()
    audit.record(db, user_id=actor.id, action="CANCEL", entity_type="sales_order", entity_id=order.id,
                 before={"status": previous.value}, after={"status": "CANCELLED"}, reason=reason,
                 summary=f"Order {order.order_no} cancelled", ip=ip)
    return order


def list_orders(db: Session, actor: User, *, status=None, customer_id=None, salesman_id=None,
                date_from=None, date_to=None, q=None, limit: int = 50, offset: int = 0):
    stmt = _scope(select(SalesOrder), actor).order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())
    if status is not None:
        stmt = stmt.where(SalesOrder.status == status)
    if customer_id is not None:
        stmt = stmt.where(SalesOrder.customer_id == customer_id)
    if salesman_id is not None:
        stmt = stmt.where(SalesOrder.salesman_id == salesman_id)
    if date_from is not None:
        stmt = stmt.where(SalesOrder.order_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(SalesOrder.order_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.join(Customer, Customer.id == SalesOrder.customer_id).where(
            or_(SalesOrder.order_no.ilike(like), Customer.name.ilike(like)))
    return paginate(db, stmt, limit, offset)


def catalog(db: Session) -> list[tuple[Product, Decimal]]:
    products = db.scalars(select(Product).join(Item, Item.id == Product.item_id).where(Item.is_active)
                          .order_by(Item.name)).all()
    return [(p, availability(db, p.item_id).available) for p in products]
