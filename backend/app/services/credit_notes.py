"""Credit notes: the only way to reduce or cancel an invoice (invoices are never deleted).

CANCELLATION     reverses everything not yet credited; invoice -> CANCELLED, order -> CANCELLED
                 (its reservation is released). If goods were dispatched, `restock` is
                 mandatory and the dispatched quantity comes back via SALES_RETURN.
SALES_RETURN     credits returned quantities at the invoiced price; with `restock` the goods
                 re-enter stock (SALES_RETURN movement at the cost they left at), otherwise
                 they are treated as written off at the customer.
PRICE_ADJUSTMENT credits a taxable amount (quantity 0), e.g. a rate dispute.

GST on a credit note follows the original invoice's supply type and line rates. A credit
note may not exceed what is still unpaid on the invoice (unallocate payments first).
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError
from app.models import (
    CreditNote,
    CreditNoteItem,
    InvoiceItem,
    Item,
    SalesOrder,
    StockMovement,
    User,
)
from app.models.enums import CreditNoteReason, DocumentType, InvoiceStatus, MovementType, OrderStatus
from app.services import audit, numbering
from app.services.inventory import post_movement
from app.services.invoicing import allocated_amount, credited_amount, get_invoice, invoice_balance

ZERO = Decimal("0.00")
QZERO = Decimal("0.0000")


@dataclass
class CreditLineIn:
    invoice_item_id: int
    quantity: Decimal = QZERO
    taxable_amount: Decimal | None = None  # PRICE_ADJUSTMENT only


def _credited(db: Session, invoice_item_id: int) -> tuple[Decimal, Decimal, Decimal]:
    """(quantity credited, taxable credited, quantity returned to stock) so far for a line."""
    qty, taxable = db.execute(select(
        func.coalesce(func.sum(CreditNoteItem.quantity), 0), func.coalesce(func.sum(CreditNoteItem.taxable_amount), 0))
        .where(CreditNoteItem.invoice_item_id == invoice_item_id)).one()
    restocked = db.scalar(select(func.coalesce(func.sum(CreditNoteItem.quantity), 0))
                          .join(CreditNote, CreditNote.id == CreditNoteItem.credit_note_id)
                          .where(CreditNoteItem.invoice_item_id == invoice_item_id, CreditNote.restock))
    return Decimal(qty), Decimal(taxable), Decimal(restocked or 0)


def _dispatch_cost(db: Session, invoice_item: InvoiceItem) -> Decimal:
    """Unit cost at which this line's goods left stock (latest SALES_DISPATCH for the order line)."""
    m = db.scalars(select(StockMovement).where(
        StockMovement.movement_type == MovementType.SALES_DISPATCH,
        StockMovement.posting_key.like(f"DSP:%:{invoice_item.order_item_id}"),
    ).order_by(StockMovement.id.desc())).first()
    return Decimal(m.unit_cost) if m else Decimal("0")


def create_credit_note(db: Session, *, invoice_id: int, reason_type: CreditNoteReason, reason: str,
                       restock: bool, lines: list[CreditLineIn], credit_date: date | None,
                       actor: User, ip: str | None = None) -> CreditNote:
    invoice = get_invoice(db, invoice_id, lock=True)
    if invoice.status == InvoiceStatus.CANCELLED:
        raise BusinessRuleError(f"Invoice {invoice.invoice_no} is already fully credited")
    when = credit_date or date.today()
    if when > date.today() or when < invoice.invoice_date:
        raise BusinessRuleError("Credit note date must be between the invoice date and today")
    order = db.get(SalesOrder, invoice.order_id)
    items = {it.id: it for it in invoice.items}
    order_lines = {li.id: li for li in order.items}

    # ---- decide quantity / taxable / tax per line -------------------------------------
    plan: list[tuple[InvoiceItem, Decimal, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    if reason_type == CreditNoteReason.CANCELLATION:
        if allocated_amount(db, invoice.id) > 0:  # receipts still applied (reversed ones don't count)
            raise BusinessRuleError("Payments are allocated to this invoice; it cannot be cancelled")
        dispatched = any(order_lines[it.order_item_id].quantity_dispatched > 0 for it in items.values())
        if dispatched and not restock:
            raise BusinessRuleError("Goods were dispatched: cancellation must restock them (restock=true)")
        for it in items.values():
            cq, ct, rq = _credited(db, it.id)
            prior = db.execute(select(
                func.coalesce(func.sum(CreditNoteItem.cgst_amount), 0), func.coalesce(func.sum(CreditNoteItem.sgst_amount), 0),
                func.coalesce(func.sum(CreditNoteItem.igst_amount), 0)).where(CreditNoteItem.invoice_item_id == it.id)).one()
            taxable = Decimal(it.taxable_amount) - ct
            if taxable <= 0:
                continue
            restock_qty = order_lines[it.order_item_id].quantity_dispatched - rq if restock else QZERO
            plan.append((it, Decimal(it.quantity) - cq, taxable, Decimal(it.cgst_amount) - Decimal(prior[0]),
                         Decimal(it.sgst_amount) - Decimal(prior[1]), Decimal(it.igst_amount) - Decimal(prior[2]),
                         max(restock_qty, QZERO)))
    else:
        if not lines:
            raise BusinessRuleError("Give at least one line to credit")
        seen = set()
        for line in lines:
            it = items.get(line.invoice_item_id)
            if it is None or line.invoice_item_id in seen:
                raise BusinessRuleError(f"Invoice line {line.invoice_item_id} is not on {invoice.invoice_no} or repeated")
            seen.add(it.id)
            cq, ct, rq = _credited(db, it.id)
            if reason_type == CreditNoteReason.SALES_RETURN:
                qty = Decimal(line.quantity)
                returnable = order_lines[it.order_item_id].quantity_dispatched - cq
                if qty <= 0 or qty > returnable:
                    raise BusinessRuleError(f"Line {it.id}: can return at most {returnable.normalize():f} "
                                            "(dispatched and not yet credited)")
                taxable = dec.money(qty * it.unit_price)
                restock_qty = qty if restock else QZERO
            else:  # PRICE_ADJUSTMENT
                qty, restock_qty = QZERO, QZERO
                taxable = dec.money(line.taxable_amount or 0)
                if taxable <= 0:
                    raise BusinessRuleError(f"Line {it.id}: taxable_amount must be positive")
            if taxable > Decimal(it.taxable_amount) - ct:
                raise BusinessRuleError(f"Line {it.id}: credit exceeds the uncredited taxable value "
                                        f"({Decimal(it.taxable_amount) - ct})")
            plan.append((it, qty, taxable, dec.money(taxable * it.cgst_rate / 100),
                         dec.money(taxable * it.sgst_rate / 100), dec.money(taxable * it.igst_rate / 100), restock_qty))

    if not plan:
        raise BusinessRuleError("Nothing left to credit on this invoice")
    total = sum((p[2] + p[3] + p[4] + p[5] for p in plan), ZERO)
    if total > invoice_balance(db, invoice):
        raise BusinessRuleError(f"Credit {total} exceeds the unpaid balance {invoice_balance(db, invoice)}; "
                                "unallocate payments first")

    # ---- write the credit note --------------------------------------------------------
    doc = numbering.next_number(db, DocumentType.CREDIT_NOTE, when)
    cn = CreditNote(credit_note_no=doc.number, financial_year=doc.financial_year, sequence_no=doc.sequence,
                    credit_note_date=when, invoice_id=invoice.id, customer_id=invoice.customer_id,
                    reason_type=reason_type, reason=reason, restock=restock, created_by=actor.id, items=[],
                    taxable_amount=ZERO, cgst_amount=ZERO, sgst_amount=ZERO, igst_amount=ZERO, total_amount=ZERO)
    for it, qty, taxable, cgst, sgst, igst, _ in plan:
        cn.items.append(CreditNoteItem(invoice_item_id=it.id, product_id=it.product_id, quantity=dec.qty(qty),
                                       taxable_amount=taxable, cgst_amount=cgst, sgst_amount=sgst,
                                       igst_amount=igst, line_total=taxable + cgst + sgst + igst))
    cn.taxable_amount = sum((i.taxable_amount for i in cn.items), ZERO)
    cn.cgst_amount = sum((i.cgst_amount for i in cn.items), ZERO)
    cn.sgst_amount = sum((i.sgst_amount for i in cn.items), ZERO)
    cn.igst_amount = sum((i.igst_amount for i in cn.items), ZERO)
    cn.total_amount = cn.taxable_amount + cn.cgst_amount + cn.sgst_amount + cn.igst_amount
    db.add(cn)
    db.flush()

    for it, _qty, _t, _c, _s, _i, restock_qty in plan:
        if restock_qty > 0:
            post_movement(
                db, item_id=it.product_id, movement_type=MovementType.SALES_RETURN, quantity=restock_qty,
                unit=db.get(Item, it.product_id).base_unit, total_value=dec.money(restock_qty * _dispatch_cost(db, it)),
                actor_id=actor.id, source_document_type="CREDIT_NOTE", source_document_id=cn.id,
                reference_no=doc.number, posting_key=f"CN:{cn.id}:{it.id}", movement_date=when,
                remarks=f"Return against {invoice.invoice_no}",
            )

    fully = credited_amount(db, invoice.id) >= invoice.total_amount
    invoice.status = InvoiceStatus.CANCELLED if fully else InvoiceStatus.PARTIALLY_CREDITED
    if reason_type == CreditNoteReason.CANCELLATION:
        order.status = OrderStatus.CANCELLED  # releases any undispatched reservation
    db.flush()
    audit.record(db, user_id=actor.id, action="CREDIT", entity_type="invoice", entity_id=invoice.id,
                 after=audit.snapshot(cn), reason=reason,
                 summary=f"{doc.number} ({reason_type.value}) {cn.total_amount} against {invoice.invoice_no}", ip=ip)
    return cn
