from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import ALL_ROLES, DbSession, client_ip, require_roles
from app.models import Customer, Item, Product, SalesOrder, Unit, User
from app.models.enums import OrderStatus, RoleCode
from app.schemas.common import Page
from app.schemas.sales import (
    ApproveIn,
    CancelIn,
    CatalogItemOut,
    OrderIn,
    OrderLineOut,
    OrderOut,
    OrderSummaryOut,
    RejectIn,
    StockCheckOut,
)
from app.services import gst
from app.services import sales as svc
from app.services.availability import check_order
from app.services.reference import get_company

router = APIRouter(prefix="/sales-orders", tags=["sales orders"])
catalog_router = APIRouter(prefix="/catalog", tags=["sales orders"])

OrderReader = Annotated[User, Depends(require_roles(RoleCode.SALESMAN, RoleCode.ADMIN, RoleCode.OWNER, RoleCode.AUDITOR))]
Salesman = Annotated[User, Depends(require_roles(RoleCode.SALESMAN))]
Admin = Annotated[User, Depends(require_roles(RoleCode.ADMIN))]
Canceller = Annotated[User, Depends(require_roles(RoleCode.SALESMAN, RoleCode.ADMIN))]

STOCK_CHECK_STATUSES = (OrderStatus.DRAFT, OrderStatus.SUBMITTED, OrderStatus.APPROVED)


def order_out(db: Session, order: SalesOrder, actor: User) -> OrderOut:
    customer = db.get(Customer, order.customer_id)
    salesman = db.get(User, order.salesman_id)
    kind = gst.supply_type(get_company(db).state_code, customer.state_code)
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    lines, taxes = [], []
    for li in order.items:
        product = db.get(Product, li.product_id)
        qty = li.quantity_approved if li.quantity_approved is not None else li.quantity_ordered
        t = gst.line_tax(qty, li.unit_price, product.gst_rate, kind)
        taxes.append(t)
        lines.append(OrderLineOut(
            id=li.id, product_id=li.product_id, product_code=product.item.code, product_name=product.item.name,
            unit_code=units[product.item.base_unit_id], quantity_ordered=li.quantity_ordered,
            quantity_approved=li.quantity_approved, quantity_dispatched=li.quantity_dispatched,
            unit_price=li.unit_price, line_amount=li.line_amount, gst_rate=t.gst_rate,
            cgst=t.cgst, sgst=t.sgst, igst=t.igst, line_total=t.total,
        ))
    tot = gst.totals(taxes)

    stock_check = None
    has_shortage = None
    if order.status in STOCK_CHECK_STATUSES:
        requested = {li.id: li.quantity_approved for li in order.items if li.quantity_approved is not None}
        checks = check_order(db, order, requested or None)
        has_shortage = any(not c.can_fulfil for c in checks)
        if actor.role.code != RoleCode.SALESMAN:  # on-hand figures are for staff
            stock_check = [StockCheckOut(
                order_item_id=c.order_item_id, product_id=c.product_id, product_code=db.get(Item, c.product_id).code,
                requested=c.requested, on_hand=c.on_hand, reserved_by_others=c.reserved_by_others,
                available=c.available, shortage=c.shortage, can_fulfil=c.can_fulfil) for c in checks]

    return OrderOut(
        id=order.id, order_no=order.order_no, customer_id=customer.id, customer_name=customer.name,
        customer_state_code=customer.state_code, salesman_id=salesman.id, salesman_name=salesman.full_name,
        order_date=order.order_date, status=order.status, remarks=order.remarks, submitted_at=order.submitted_at,
        reviewed_by=order.reviewed_by, reviewed_at=order.reviewed_at, rejection_reason=order.rejection_reason,
        version=order.version, supply_type=kind, taxable_amount=tot.taxable, cgst_amount=tot.cgst,
        sgst_amount=tot.sgst, igst_amount=tot.igst, total_amount=tot.total, has_shortage=has_shortage,
        items=lines, stock_check=stock_check,
    )


@catalog_router.get("", response_model=list[CatalogItemOut])
def catalog(db: DbSession, _: Annotated[User, Depends(require_roles(*ALL_ROLES))]):
    """Price list with currently available (unreserved) stock."""
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    return [CatalogItemOut(product_id=p.item_id, code=p.item.code, name=p.item.name,
                           unit_code=units[p.item.base_unit_id], hsn_code=p.hsn_code, gst_rate=p.gst_rate,
                           selling_price=p.selling_price, available=avail)
            for p, avail in svc.catalog(db)]


@router.get("", response_model=Page[OrderSummaryOut])
def list_orders(
    db: DbSession, actor: OrderReader,
    status_: Annotated[OrderStatus | None, Query(alias="status")] = None,
    customer_id: int | None = None, salesman_id: int | None = None,
    date_from: date | None = None, date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0,
):
    """Salesmen see only their own orders. `status=SUBMITTED` is the admin approval queue."""
    rows, total = svc.list_orders(db, actor, status=status_, customer_id=customer_id, salesman_id=salesman_id,
                                  date_from=date_from, date_to=date_to, q=q, limit=limit, offset=offset)
    items = []
    for o in rows:
        shortage = None
        if o.status == OrderStatus.SUBMITTED:
            shortage = any(not c.can_fulfil for c in check_order(db, o))
        items.append(OrderSummaryOut(
            id=o.id, order_no=o.order_no, customer_id=o.customer_id, customer_name=db.get(Customer, o.customer_id).name,
            salesman_id=o.salesman_id, order_date=o.order_date, status=o.status,
            taxable_amount=sum((li.line_amount for li in o.items), start=0), has_shortage=shortage))
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderOut)
def get_order(order_id: int, db: DbSession, actor: OrderReader):
    return order_out(db, svc.get_order(db, order_id, actor), actor)


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
def create_order(data: OrderIn, db: DbSession, actor: Salesman, request: Request):
    return order_out(db, svc.create_order(db, data, actor, client_ip(request)), actor)


@router.put("/{order_id}", response_model=OrderOut)
def update_order(order_id: int, data: OrderIn, db: DbSession, actor: Salesman, request: Request):
    return order_out(db, svc.update_order(db, order_id, data, actor, client_ip(request)), actor)


@router.post("/{order_id}/submit", response_model=OrderOut)
def submit_order(order_id: int, db: DbSession, actor: Salesman, request: Request):
    return order_out(db, svc.submit_order(db, order_id, actor, client_ip(request)), actor)


@router.post("/{order_id}/approve", response_model=OrderOut)
def approve_order(order_id: int, data: ApproveIn, db: DbSession, actor: Admin, request: Request):
    """Approve as ordered, or with reduced quantities / corrected prices (reason required)."""
    return order_out(db, svc.approve_order(db, order_id, data, actor, client_ip(request)), actor)


@router.post("/{order_id}/reject", response_model=OrderOut)
def reject_order(order_id: int, data: RejectIn, db: DbSession, actor: Admin, request: Request):
    return order_out(db, svc.reject_order(db, order_id, data.version, data.reason, actor, client_ip(request)), actor)


@router.post("/{order_id}/cancel", response_model=OrderOut)
def cancel_order(order_id: int, data: CancelIn, db: DbSession, actor: Canceller, request: Request):
    return order_out(db, svc.cancel_order(db, order_id, data.reason, actor, client_ip(request)), actor)
