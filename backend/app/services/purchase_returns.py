"""Purchase returns: goods sent back to the supplier, recorded as a debit note (DN/2026-27/00001).

* Only against a POSTED purchase, line by line, up to what was received minus earlier returns.
  The purchase row is locked, so two returns at once cannot over-return.
* The supplier is debited at the original purchase rate with the same GST split. Returning the
  rest of a line uses its exact remaining value, so totals never drift by a paisa.
* Goods leave stock through the ledger (PURCHASE_RETURN): no negative stock, one posting per
  line (posting key), valued at the current weighted-average cost like every issue.
* Created and posted in one step; never edited or deleted (like credit notes).
"""
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Item, Purchase, PurchaseItem, PurchaseReturn, PurchaseReturnItem, Supplier, User
from app.models.enums import DocumentStatus, DocumentType, MovementType, UnitDimension
from app.schemas.purchases import PurchaseReturnIn
from app.services import audit, numbering
from app.services.inventory import post_movement
from app.services.units import convert, get_unit

ZERO_Q = Decimal("0.0000")
ZERO_M = Decimal("0.00")


def returned(db: Session, purchase_item_id: int) -> tuple[Decimal, Decimal, Decimal]:
    """(quantity, taxable, tax) already returned for a purchase line."""
    q, t, x = db.execute(select(
        func.coalesce(func.sum(PurchaseReturnItem.quantity), 0),
        func.coalesce(func.sum(PurchaseReturnItem.taxable_amount), 0),
        func.coalesce(func.sum(PurchaseReturnItem.tax_amount), 0),
    ).where(PurchaseReturnItem.purchase_item_id == purchase_item_id)).one()
    return dec.qty(Decimal(q)), dec.money(Decimal(t)), dec.money(Decimal(x))


def create_return(db: Session, purchase_id: int, data: PurchaseReturnIn, actor: User,
                  ip: str | None = None) -> PurchaseReturn:
    purchase = db.scalars(select(Purchase).where(Purchase.id == purchase_id)
                          .with_for_update().execution_options(populate_existing=True)).first()
    if purchase is None:
        raise NotFoundError(f"Purchase {purchase_id} not found")
    if purchase.status != DocumentStatus.POSTED:
        raise BusinessRuleError(f"Purchase {purchase.purchase_no} is {purchase.status.value}; "
                                "only posted purchases can be returned (cancel a draft instead)")
    when = data.return_date or date.today()
    if when > date.today():
        raise BusinessRuleError("Return date cannot be in the future")
    if when < purchase.received_date:
        raise BusinessRuleError(f"Return date cannot be before the goods were received ({purchase.received_date})")
    ids = [ln.purchase_item_id for ln in data.items]
    if len(ids) != len(set(ids)):
        raise BusinessRuleError("Each purchase line may appear only once in a return")

    lines = {li.id: li for li in purchase.items}
    intra_state = purchase.igst_amount == 0  # same GST split as the original bill
    supplier = db.get(Supplier, purchase.supplier_id)

    # Pass 1: validate and price every line (nothing written yet).
    planned = []
    totals = {"taxable": ZERO_M, "cgst": ZERO_M, "sgst": ZERO_M, "igst": ZERO_M}
    for ln in data.items:
        line: PurchaseItem | None = lines.get(ln.purchase_item_id)
        if line is None:
            raise BusinessRuleError(f"Line {ln.purchase_item_id} does not belong to purchase {purchase.purchase_no}")
        item = db.get(Item, line.item_id)
        unit = get_unit(db, line.unit_id)
        done_q, done_t, done_x = returned(db, line.id)
        remaining = line.quantity - done_q
        if ln.quantity > remaining:
            raise BusinessRuleError(
                f"{item.code}: cannot return {_n(ln.quantity)} {unit.code}; received {_n(line.quantity)}, "
                f"already returned {_n(done_q)}, so at most {_n(remaining)} can go back",
                {"purchase_item_id": line.id, "remaining": str(remaining)})
        if unit.dimension == UnitDimension.COUNT and ln.quantity != ln.quantity.to_integral_value():
            raise BusinessRuleError(f"{item.code} is counted in {unit.code}; return a whole number")
        if ln.quantity == remaining:  # the rest of the line: exact remaining value, no rounding drift
            taxable = dec.money(line.taxable_amount - done_t)
            tax = dec.money(line.tax_amount - done_x)
        else:
            taxable = dec.money(ln.quantity * line.rate)
            if intra_state:  # each half rounded on its own, as on the bill
                tax = dec.money(taxable * line.gst_rate / 200) * 2
            else:
                tax = dec.money(taxable * line.gst_rate / 100)
        if taxable <= 0:
            raise BusinessRuleError(f"{item.code}: nothing left to return")
        cgst = dec.money(tax / 2) if intra_state else ZERO_M
        sgst = tax - cgst if intra_state else ZERO_M
        totals["taxable"] += taxable
        totals["cgst"] += cgst
        totals["sgst"] += sgst
        totals["igst"] += ZERO_M if intra_state else tax
        planned.append((line, item, unit, ln.quantity, taxable, tax))

    # Pass 2: the debit note, then one ledger posting per line.
    doc = numbering.next_number(db, DocumentType.DEBIT_NOTE, when)
    ret = PurchaseReturn(return_no=doc.number, purchase_id=purchase.id, supplier_id=purchase.supplier_id,
                         return_date=when, reason=data.reason.strip(), created_by=actor.id, items=[],
                         taxable_amount=totals["taxable"], cgst_amount=totals["cgst"], sgst_amount=totals["sgst"],
                         igst_amount=totals["igst"], total_amount=sum(totals.values(), ZERO_M), stock_value=ZERO_M)
    db.add(ret)
    db.flush()
    stock_total = ZERO_M
    for line, item, unit, qty, taxable, tax in planned:
        movement = post_movement(
            db, item_id=line.item_id, movement_type=MovementType.PURCHASE_RETURN, quantity=qty, unit=unit,
            actor_id=actor.id, source_document_type="PURCHASE_RETURN", source_document_id=ret.id,
            reference_no=ret.return_no, posting_key=f"PRT:{ret.id}:LINE:{line.id}", movement_date=when,
            remarks=f"Returned to {supplier.name} against {purchase.purchase_no}",
        )
        stock_value = -movement.value
        stock_total += stock_value
        ret.items.append(PurchaseReturnItem(
            purchase_item_id=line.id, item_id=line.item_id, quantity=qty,
            base_quantity=convert(db, qty, unit, item.base_unit, item.id),
            taxable_amount=taxable, tax_amount=tax, line_total=taxable + tax, stock_value=stock_value))
    ret.stock_value = stock_total
    db.flush()
    audit.record(db, user_id=actor.id, action="RETURN", entity_type="purchase_return", entity_id=ret.id,
                 after={**audit.snapshot(ret), "lines": [{"purchase_item_id": i.purchase_item_id,
                                                          "quantity": str(i.quantity)} for i in ret.items]},
                 reason=ret.reason,
                 summary=f"{ret.return_no}: goods returned to {supplier.name} against {purchase.purchase_no} "
                         f"(debit {ret.total_amount})", ip=ip)
    return ret


def list_returns(db: Session, purchase_id: int) -> list[PurchaseReturn]:
    if db.get(Purchase, purchase_id) is None:
        raise NotFoundError(f"Purchase {purchase_id} not found")
    return list(db.scalars(select(PurchaseReturn).where(PurchaseReturn.purchase_id == purchase_id)
                           .order_by(PurchaseReturn.id)))


def _n(q: Decimal) -> str:
    return f"{q.normalize():f}"

