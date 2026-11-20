"""Customer credit control, checked when an admin approves an order.

    exposure = net outstanding      (open invoice balances - unallocated advances)
             + open orders          (approved, not yet invoiced, incl. GST)
             + this order           (at the quantities/prices being approved, incl. GST)

A customer with credit_limit = 0 has no limit. Above the limit, approval is refused unless the
admin records a credit-override reason (audited). Invoices past the customer's credit days are
reported as overdue (a warning shown to the admin), not blocked.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError
from app.models import Customer, Product, SalesOrder
from app.models.enums import OrderStatus
from app.services import gst
from app.services.payments import receivables
from app.services.reference import get_company

ZERO = Decimal("0.00")


class CreditLimitError(BusinessRuleError):
    code = "credit_limit_exceeded"


@dataclass(frozen=True)
class CreditPosition:
    limit: Decimal
    credit_days: int
    outstanding: Decimal  # net receivable (advances deducted)
    open_orders: Decimal  # approved but not yet invoiced, other orders
    this_order: Decimal
    overdue: Decimal  # invoice balances older than credit_days
    oldest_overdue_days: int | None

    @property
    def unlimited(self) -> bool:
        return self.limit == 0

    @property
    def exposure(self) -> Decimal:
        return self.outstanding + self.open_orders + self.this_order

    @property
    def available(self) -> Decimal | None:
        """Credit left before this order (None = no limit). Can be negative."""
        return None if self.unlimited else self.limit - self.outstanding - self.open_orders

    @property
    def exceeds(self) -> bool:
        return not self.unlimited and self.exposure > self.limit

    @property
    def excess(self) -> Decimal:
        return max(self.exposure - self.limit, ZERO) if not self.unlimited else ZERO

    def details(self) -> dict[str, str | int | None]:
        return {"limit": str(self.limit), "outstanding": str(self.outstanding), "open_orders": str(self.open_orders),
                "this_order": str(self.this_order), "exposure": str(self.exposure), "excess": str(self.excess),
                "overdue": str(self.overdue), "oldest_overdue_days": self.oldest_overdue_days}


def order_value(db: Session, order: SalesOrder, quantities: dict[int, Decimal] | None = None,
                prices: dict[int, Decimal] | None = None) -> Decimal:
    """Order total incl. GST, at the given (or currently approved / ordered) quantities and prices."""
    customer = db.get(Customer, order.customer_id)
    kind = gst.supply_type(get_company(db).state_code, customer.state_code)
    taxes = []
    for li in order.items:
        if quantities is not None:
            qty = quantities.get(li.id, li.quantity_ordered)
        else:
            qty = li.quantity_approved if li.quantity_approved is not None else li.quantity_ordered
        price = (prices or {}).get(li.id, li.unit_price)
        taxes.append(gst.line_tax(qty, price, db.get(Product, li.product_id).gst_rate, kind))
    return gst.totals(taxes).total


def position(db: Session, customer: Customer, *, this_order: Decimal = ZERO,
             exclude_order_id: int | None = None, as_of: date | None = None) -> CreditPosition:
    as_of = as_of or date.today()
    rec = next(iter(receivables(db, as_of=as_of, customer_id=customer.id)), None)
    outstanding = rec.outstanding if rec else ZERO
    overdue, oldest = ZERO, None
    if rec:
        for _inv, bal, days in rec.open_invoices:
            if days > customer.credit_days:
                overdue += bal
                oldest = max(oldest or 0, days)
    stmt = select(SalesOrder).where(SalesOrder.customer_id == customer.id, SalesOrder.status == OrderStatus.APPROVED)
    if exclude_order_id is not None:
        stmt = stmt.where(SalesOrder.id != exclude_order_id)
    open_orders = sum((order_value(db, o) for o in db.scalars(stmt)), ZERO)
    return CreditPosition(limit=customer.credit_limit, credit_days=customer.credit_days, outstanding=outstanding,
                          open_orders=open_orders, this_order=this_order, overdue=overdue, oldest_overdue_days=oldest)
