"""GST tax invoices.

* One invoice per approved order, for the approved quantities (it is the bill for the goods
  the admin committed to supply). The order moves to INVOICED.
* Numbering: INV/<FY>/<seq>, gap-free per financial year, and invoice dates must not go
  backwards within a series (invoice numbers must be chronological).
* Customer name, GSTIN, address and place of supply are SNAPSHOT onto the invoice.
* GST per line via services.gst: intra-state CGST+SGST, inter-state IGST.
* Invoices are never deleted or edited: corrections go through credit notes.

Balance (outstanding) of an invoice = total - credit notes - payment allocations.
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import (
    CreditNote,
    Customer,
    Invoice,
    InvoiceItem,
    Payment,
    PaymentAllocation,
    Product,
    SalesOrder,
    User,
)
from app.models.enums import DocumentType, InvoiceStatus, OrderStatus
from app.services import audit, gst, numbering
from app.services.availability import check_order
from app.services.common import paginate
from app.services.reference import get_company

ZERO = Decimal("0.00")


def get_invoice(db: Session, invoice_id: int, lock: bool = False) -> Invoice:
    stmt = select(Invoice).where(Invoice.id == invoice_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    inv = db.scalars(stmt).first()
    if inv is None:
        raise NotFoundError(f"Invoice {invoice_id} not found")
    return inv


def credited_amount(db: Session, invoice_id: int) -> Decimal:
    return dec.money(Decimal(db.scalar(select(func.coalesce(func.sum(CreditNote.total_amount), 0))
                                       .where(CreditNote.invoice_id == invoice_id)) or 0))


def allocated_amount(db: Session, invoice_id: int) -> Decimal:
    """Receipts applied to the invoice; allocations of reversed receipts no longer count."""
    return dec.money(Decimal(db.scalar(select(func.coalesce(func.sum(PaymentAllocation.amount), 0))
                                       .join(Payment, Payment.id == PaymentAllocation.payment_id)
                                       .where(PaymentAllocation.invoice_id == invoice_id,
                                              Payment.reversed_on.is_(None))) or 0))


def invoice_balance(db: Session, invoice: Invoice) -> Decimal:
    return (Decimal(invoice.total_amount) - credited_amount(db, invoice.id) - allocated_amount(db, invoice.id)).quantize(Decimal("0.01"))


def create_invoice(db: Session, order_id: int, invoice_date: date | None, actor: User, ip: str | None = None) -> Invoice:
    order = db.scalars(select(SalesOrder).where(SalesOrder.id == order_id).with_for_update().execution_options(populate_existing=True)).first()
    if order is None:
        raise NotFoundError(f"Sales order {order_id} not found")
    if order.status != OrderStatus.APPROVED:
        raise BusinessRuleError(f"Order {order.order_no} is {order.status.value}; only approved orders can be invoiced")
    when = invoice_date or date.today()
    if when > date.today():
        raise BusinessRuleError("Invoice date cannot be in the future")
    if when < order.order_date:
        raise BusinessRuleError("Invoice date cannot be before the order date")

    lines = [li for li in order.items if li.quantity_approved and li.quantity_approved > 0]
    # Reservation guarantees availability, but re-check defensively before billing goods.
    for check in check_order(db, order, {li.id: li.quantity_approved for li in lines}):
        if not check.can_fulfil:
            raise BusinessRuleError(f"Stock for line {check.order_item_id} is no longer available "
                                    f"(short by {check.shortage.normalize():f})", {"shortage": str(check.shortage)})

    company = get_company(db)
    customer = db.get(Customer, order.customer_id)
    kind = gst.supply_type(company.state_code, customer.state_code)

    doc = numbering.next_number(db, DocumentType.INVOICE, when)
    last_date = db.scalar(select(func.max(Invoice.invoice_date)).where(Invoice.financial_year == doc.financial_year))
    if last_date is not None and when < last_date:
        raise BusinessRuleError(f"Invoice date {when} is before the last invoice in this series ({last_date})")

    invoice = Invoice(
        invoice_no=doc.number, financial_year=doc.financial_year, sequence_no=doc.sequence, invoice_date=when,
        order_id=order.id, customer_id=customer.id, customer_name=customer.name, customer_gstin=customer.gstin,
        billing_address=customer.address, place_of_supply_state_code=customer.state_code,
        supplier_state_code=company.state_code, supply_type=kind, status=InvoiceStatus.ISSUED,
        created_by=actor.id, round_off=ZERO, items=[],
    )
    taxes = []
    for li in lines:
        product = db.get(Product, li.product_id)
        t = gst.line_tax(li.quantity_approved, li.unit_price, product.gst_rate, kind)
        taxes.append(t)
        invoice.items.append(InvoiceItem(
            order_item_id=li.id, product_id=li.product_id, description=product.item.name, hsn_code=product.hsn_code,
            quantity=li.quantity_approved, unit_id=product.item.base_unit_id, unit_price=li.unit_price,
            taxable_amount=t.taxable, gst_rate=t.gst_rate, cgst_rate=t.cgst_rate, cgst_amount=t.cgst,
            sgst_rate=t.sgst_rate, sgst_amount=t.sgst, igst_rate=t.igst_rate, igst_amount=t.igst, line_total=t.total,
        ))
    tot = gst.totals(taxes)
    invoice.taxable_amount, invoice.cgst_amount = tot.taxable, tot.cgst
    invoice.sgst_amount, invoice.igst_amount = tot.sgst, tot.igst
    invoice.total_amount = tot.total  # round_off kept at 0: totals are exact to the paisa
    db.add(invoice)
    order.status = OrderStatus.INVOICED
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="invoice", entity_id=invoice.id,
                 after=audit.snapshot(invoice), summary=f"Invoice {invoice.invoice_no} for {order.order_no}", ip=ip)
    return invoice


def list_invoices(db: Session, *, customer_id=None, order_id=None, status=None, date_from=None, date_to=None, q=None,
                  limit: int = 50, offset: int = 0):
    stmt = select(Invoice).order_by(Invoice.invoice_date.desc(), Invoice.id.desc())
    if order_id is not None:
        stmt = stmt.where(Invoice.order_id == order_id)
    if customer_id is not None:
        stmt = stmt.where(Invoice.customer_id == customer_id)
    if status is not None:
        stmt = stmt.where(Invoice.status == status)
    if date_from is not None:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Invoice.invoice_no.ilike(like), Invoice.customer_name.ilike(like)))
    return paginate(db, stmt, limit, offset)
