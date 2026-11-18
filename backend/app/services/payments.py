"""Customer receipts, allocation to invoices, and receivables (outstanding + ageing).

* A receipt is allocated to invoices either explicitly or automatically, oldest invoice
  first (FIFO). Allocation can never exceed an invoice's unpaid balance; whatever is left
  stays on the customer's account as an unallocated advance.
* Customer outstanding = sum of invoice balances - unallocated advances.
  Benchmark: Retailer A 7,875.00 - 4,000.00 = 3,875.00.
* Ageing buckets come from settings (`receivable_ageing_buckets`, default 30,60,90) and
  are measured in days since invoice date.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Customer, Invoice, Payment, PaymentAllocation, User
from app.models.enums import DocumentType, InvoiceStatus, PaymentMode
from app.services import audit, numbering
from app.services.common import paginate
from app.services.invoicing import invoice_balance
from app.services.reference import get_setting

ZERO = Decimal("0.00")


def open_invoices(db: Session, customer_id: int, lock: bool = False) -> list[tuple[Invoice, Decimal]]:
    stmt = (select(Invoice).where(Invoice.customer_id == customer_id, Invoice.status != InvoiceStatus.CANCELLED)
            .order_by(Invoice.invoice_date, Invoice.id))
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    out = []
    for inv in db.scalars(stmt):
        bal = invoice_balance(db, inv)
        if bal > 0:
            out.append((inv, bal))
    return out


def record_payment(db: Session, *, customer_id: int, payment_date: date, amount: Decimal, mode: PaymentMode,
                   reference_no: str | None, remarks: str | None, allocations: list[tuple[int, Decimal]] | None,
                   actor: User, ip: str | None = None) -> Payment:
    customer = db.get(Customer, customer_id)
    if customer is None:
        raise NotFoundError(f"Customer {customer_id} not found")
    if payment_date > date.today():
        raise BusinessRuleError("Payment date cannot be in the future")
    amount = dec.money(amount)
    if amount <= 0:
        raise BusinessRuleError("Amount must be positive")

    open_inv = open_invoices(db, customer.id, lock=True)
    balances = {inv.id: bal for inv, bal in open_inv}
    if allocations is None:  # automatic FIFO: oldest invoice first
        allocations, left = [], amount
        for inv, bal in open_inv:
            if left <= 0:
                break
            take = min(bal, left)
            allocations.append((inv.id, take))
            left -= take
    else:
        if sum((a for _, a in allocations), ZERO) > amount:
            raise BusinessRuleError("Allocations exceed the amount received")
        for inv_id, amt in allocations:
            if inv_id not in balances:
                raise BusinessRuleError(f"Invoice {inv_id} is not an open invoice of {customer.name}")
            if amt <= 0 or amt > balances[inv_id]:
                raise BusinessRuleError(f"Allocation {amt} to invoice {inv_id} exceeds its balance {balances[inv_id]}")

    doc = numbering.next_number(db, DocumentType.RECEIPT, payment_date)
    payment = Payment(receipt_no=doc.number, customer_id=customer.id, payment_date=payment_date, amount=amount,
                      mode=mode, reference_no=reference_no, remarks=remarks, received_by=actor.id,
                      allocations=[PaymentAllocation(invoice_id=i, amount=dec.money(a)) for i, a in allocations])
    db.add(payment)
    db.flush()
    audit.record(db, user_id=actor.id, action="RECEIPT", entity_type="payment", entity_id=payment.id,
                 after={**audit.snapshot(payment),
                        "allocations": [{"invoice_id": i, "amount": str(a)} for i, a in allocations]},
                 summary=f"{doc.number}: {amount} from {customer.name}", ip=ip)
    return payment


def unallocated(db: Session, payment: Payment) -> Decimal:
    return payment.amount - sum((a.amount for a in payment.allocations), ZERO)


def list_payments(db: Session, *, customer_id=None, date_from=None, date_to=None, limit=50, offset=0):
    stmt = select(Payment).order_by(Payment.payment_date.desc(), Payment.id.desc())
    if customer_id is not None:
        stmt = stmt.where(Payment.customer_id == customer_id)
    if date_from is not None:
        stmt = stmt.where(Payment.payment_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Payment.payment_date <= date_to)
    return paginate(db, stmt, limit, offset)


# ---- receivables ------------------------------------------------------------------------
def bucket_labels(bounds: list[int]) -> list[str]:
    labels, lo = [], 0
    for b in bounds:
        labels.append(f"{lo}-{b}")
        lo = b + 1
    return [*labels, f"{bounds[-1]}+"]


@dataclass
class CustomerReceivable:
    customer: Customer
    invoiced: Decimal = ZERO
    credited: Decimal = ZERO
    received: Decimal = ZERO
    invoice_outstanding: Decimal = ZERO
    unallocated: Decimal = ZERO
    buckets: dict[str, Decimal] = field(default_factory=dict)
    open_invoices: list[tuple[Invoice, Decimal, int]] = field(default_factory=list)

    @property
    def outstanding(self) -> Decimal:
        """Net amount due (an unallocated advance reduces it)."""
        return self.invoice_outstanding - self.unallocated


def receivables(db: Session, as_of: date | None = None, customer_id: int | None = None) -> list[CustomerReceivable]:
    as_of = as_of or date.today()
    bounds = [int(x) for x in get_setting(db, "receivable_ageing_buckets").split(",")]
    labels = bucket_labels(bounds)
    stmt = select(Customer).order_by(Customer.name)
    if customer_id is not None:
        stmt = stmt.where(Customer.id == customer_id)
    result = []
    for cust in db.scalars(stmt):
        r = CustomerReceivable(cust, buckets={label: ZERO for label in labels})
        invoices = db.scalars(select(Invoice).where(Invoice.customer_id == cust.id, Invoice.invoice_date <= as_of)
                              .order_by(Invoice.invoice_date)).all()
        for inv in invoices:
            r.invoiced += inv.total_amount
            bal = invoice_balance(db, inv)
            r.credited += inv.total_amount - bal - _allocated(db, inv.id)
            if bal > 0:
                days = (as_of - inv.invoice_date).days
                idx = next((i for i, b in enumerate(bounds) if days <= b), len(bounds))
                r.buckets[labels[idx]] += bal
                r.invoice_outstanding += bal
                r.open_invoices.append((inv, bal, days))
        payments = db.scalars(select(Payment).where(Payment.customer_id == cust.id, Payment.payment_date <= as_of)).all()
        r.received = sum((p.amount for p in payments), ZERO)
        r.unallocated = sum((unallocated(db, p) for p in payments), ZERO)
        if invoices or payments:
            result.append(r)
    return result


def _allocated(db: Session, invoice_id: int) -> Decimal:
    return Decimal(db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
                             .where(PaymentAllocation.invoice_id == invoice_id)) or 0)
