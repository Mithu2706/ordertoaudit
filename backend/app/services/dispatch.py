"""Dispatch: ship invoiced goods. Each line posts a SALES_DISPATCH movement (weighted-average
cost) through the ledger, so stock can never go negative and a dispatch is all-or-nothing.

Rules
* Only INVOICED / PARTIALLY_DISPATCHED orders can be dispatched (invoice before goods leave).
* A line can never ship more than approved - already dispatched: an "invalid full dispatch"
  (e.g. Distributor B's 120 when 88 were approved) is impossible.
* Partial dispatches are allowed; the order becomes PARTIALLY_DISPATCHED, then DISPATCHED.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Dispatch, DispatchItem, Invoice, Item, SalesOrder, User
from app.models.enums import DispatchStatus, DocumentType, InvoiceStatus, MovementType, OrderStatus
from app.services import audit, numbering
from app.services.common import paginate
from app.services.inventory import post_movement

DISPATCHABLE = (OrderStatus.INVOICED, OrderStatus.PARTIALLY_DISPATCHED)


def create_dispatch(db: Session, *, order_id: int, lines: dict[int, Decimal] | None, dispatch_date: date | None,
                    vehicle_no: str | None, transporter: str | None, remarks: str | None,
                    actor: User, ip: str | None = None) -> Dispatch:
    order = db.scalars(select(SalesOrder).where(SalesOrder.id == order_id).with_for_update()).first()
    if order is None:
        raise NotFoundError(f"Sales order {order_id} not found")
    if order.status not in DISPATCHABLE:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value}; it must be invoiced before dispatch")
    invoice = db.scalars(select(Invoice).where(Invoice.order_id == order.id, Invoice.status != InvoiceStatus.CANCELLED)
                         .order_by(Invoice.id.desc())).first()
    if invoice is None:
        raise BusinessRuleError(f"Order {order.order_no} has no live invoice")
    when = dispatch_date or date.today()
    if when > date.today() or when < invoice.invoice_date:
        raise BusinessRuleError("Dispatch date must be between the invoice date and today")

    by_id = {li.id: li for li in order.items}
    pending = {li.id: (li.quantity_approved or 0) - li.quantity_dispatched for li in order.items}
    wanted = lines if lines else {i: q for i, q in pending.items() if q > 0}
    for line_id, qty in wanted.items():
        if line_id not in by_id:
            raise BusinessRuleError(f"Line {line_id} does not belong to order {order.order_no}")
        if qty <= 0:
            raise BusinessRuleError(f"Line {line_id}: quantity must be positive")
        if qty > pending[line_id]:
            raise BusinessRuleError(
                f"Line {line_id}: cannot dispatch {qty.normalize():f}; only {pending[line_id].normalize():f} "
                "approved and not yet dispatched",
                {"order_item_id": line_id, "requested": str(qty), "dispatchable": str(pending[line_id])})
    if not wanted:
        raise BusinessRuleError(f"Nothing left to dispatch on order {order.order_no}")

    doc = numbering.next_number(db, DocumentType.DISPATCH, when)
    dispatch = Dispatch(dispatch_no=doc.number, order_id=order.id, invoice_id=invoice.id, dispatch_date=when,
                        status=DispatchStatus.DISPATCHED, vehicle_no=vehicle_no, transporter=transporter,
                        remarks=remarks, created_by=actor.id, items=[])
    db.add(dispatch)
    db.flush()
    for line_id, qty in sorted(wanted.items()):
        li = by_id[line_id]
        dispatch.items.append(DispatchItem(order_item_id=li.id, product_id=li.product_id, quantity=qty))
        post_movement(
            db, item_id=li.product_id, movement_type=MovementType.SALES_DISPATCH, quantity=qty,
            unit=db.get(Item, li.product_id).base_unit, actor_id=actor.id, source_document_type="DISPATCH",
            source_document_id=dispatch.id, reference_no=doc.number, posting_key=f"DSP:{dispatch.id}:{li.id}",
            movement_date=when, remarks=f"{order.order_no} / {invoice.invoice_no}",
        )
        li.quantity_dispatched += qty
    fully = all(li.quantity_dispatched >= (li.quantity_approved or 0) for li in order.items)
    order.status = OrderStatus.DISPATCHED if fully else OrderStatus.PARTIALLY_DISPATCHED
    db.flush()
    audit.record(db, user_id=actor.id, action="DISPATCH", entity_type="dispatch", entity_id=dispatch.id,
                 after={**audit.snapshot(dispatch), "lines": {str(k): str(v) for k, v in wanted.items()}},
                 summary=f"{doc.number} for {order.order_no} ({order.status.value})", ip=ip)
    return dispatch


def get_dispatch(db: Session, dispatch_id: int) -> Dispatch:
    d = db.get(Dispatch, dispatch_id)
    if d is None:
        raise NotFoundError(f"Dispatch {dispatch_id} not found")
    return d


def list_dispatches(db: Session, *, order_id=None, date_from=None, date_to=None, limit=50, offset=0):
    stmt = select(Dispatch).order_by(Dispatch.dispatch_date.desc(), Dispatch.id.desc())
    if order_id is not None:
        stmt = stmt.where(Dispatch.order_id == order_id)
    if date_from is not None:
        stmt = stmt.where(Dispatch.dispatch_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Dispatch.dispatch_date <= date_to)
    return paginate(db, stmt, limit, offset)
