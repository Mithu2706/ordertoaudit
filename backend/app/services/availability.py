"""Finished-goods availability for sales.

    available = on hand (from the ledger) - reserved
    reserved  = approved quantity not yet dispatched, on orders that are
                APPROVED / INVOICED / PARTIALLY_DISPATCHED

Approval is the commitment point: once Retailer A's 150 packets are approved they are
reserved, so Distributor B sees only 88 available, before or after A is dispatched.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import SalesOrder, SalesOrderItem
from app.models.enums import OrderStatus
from app.services.inventory import current_balance

ZERO = Decimal("0.0000")  # quantity scale, so "no shortage" prints as 0.0000
RESERVING_STATUSES = (OrderStatus.APPROVED, OrderStatus.INVOICED, OrderStatus.PARTIALLY_DISPATCHED)


@dataclass(frozen=True)
class Availability:
    product_id: int
    on_hand: Decimal
    reserved: Decimal

    @property
    def available(self) -> Decimal:
        return max(self.on_hand - self.reserved, ZERO)


def reserved_quantity(db: Session, product_id: int, exclude_order_id: int | None = None) -> Decimal:
    stmt = (
        select(func.coalesce(func.sum(SalesOrderItem.quantity_approved - SalesOrderItem.quantity_dispatched), 0))
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(SalesOrderItem.product_id == product_id, SalesOrder.status.in_(RESERVING_STATUSES))
    )
    if exclude_order_id is not None:
        stmt = stmt.where(SalesOrder.id != exclude_order_id)
    return Decimal(db.scalar(stmt) or 0)


def availability(db: Session, product_id: int, exclude_order_id: int | None = None) -> Availability:
    return Availability(product_id, current_balance(db, product_id).quantity,
                        reserved_quantity(db, product_id, exclude_order_id))


@dataclass(frozen=True)
class LineCheck:
    order_item_id: int
    product_id: int
    requested: Decimal
    on_hand: Decimal
    reserved_by_others: Decimal
    available: Decimal

    @property
    def shortage(self) -> Decimal:
        return max(self.requested - self.available, ZERO)

    @property
    def can_fulfil(self) -> bool:
        return self.shortage == 0


def check_order(db: Session, order: SalesOrder, requested: dict[int, Decimal] | None = None) -> list[LineCheck]:
    """Stock check for each line. `requested` maps order_item_id -> qty (default: ordered qty)."""
    checks = []
    for line in order.items:
        a = availability(db, line.product_id, exclude_order_id=order.id)
        qty = requested.get(line.id, line.quantity_ordered) if requested else line.quantity_ordered
        checks.append(LineCheck(line.id, line.product_id, Decimal(qty), a.on_hand, a.reserved, a.available))
    return checks
