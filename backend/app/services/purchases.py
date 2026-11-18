"""Purchases: draft -> posted (stock received) or cancelled.

Inventory cost of a purchase line = its TAXABLE value. GST paid on purchases is input
tax credit for a registered manufacturer, so it is not part of stock cost.
Input tax split: supplier in the factory's state -> CGST + SGST, otherwise IGST.
"""
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.models import Item, Purchase, PurchaseItem, Supplier, User
from app.models.enums import DocumentStatus, DocumentType, ItemType, MovementType
from app.schemas.purchases import PurchaseIn
from app.services import audit, numbering
from app.services.common import paginate
from app.services.inventory import post_movement
from app.services.reference import get_company
from app.services.units import convert, get_unit

STOCKABLE_PURCHASE_TYPES = {ItemType.RAW_MATERIAL, ItemType.PACKAGING}


def _get(db: Session, purchase_id: int, lock: bool = False) -> Purchase:
    stmt = select(Purchase).where(Purchase.id == purchase_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    p = db.scalars(stmt).first()
    if p is None:
        raise NotFoundError(f"Purchase {purchase_id} not found")
    return p


def get_purchase(db: Session, purchase_id: int) -> Purchase:
    return _get(db, purchase_id)


def _apply(db: Session, purchase: Purchase, data: PurchaseIn) -> None:
    """Validate and (re)build header + lines with GST computed per line."""
    supplier = db.get(Supplier, data.supplier_id)
    if supplier is None or not supplier.is_active:
        raise BusinessRuleError("Supplier not found or inactive", {"field": "supplier_id"})
    dup = db.scalars(select(Purchase.id).where(
        Purchase.supplier_id == supplier.id, Purchase.supplier_invoice_no == data.supplier_invoice_no,
        Purchase.id != (purchase.id or 0))).first()
    if dup is not None:
        raise ConflictError(f"Supplier bill '{data.supplier_invoice_no}' is already recorded", {"purchase_id": dup})

    intra_state = supplier.state_code == get_company(db).state_code
    purchase.supplier_id = supplier.id
    purchase.supplier_invoice_no = data.supplier_invoice_no
    purchase.supplier_invoice_date = data.supplier_invoice_date
    purchase.received_date = data.received_date
    purchase.notes = data.notes
    purchase.items.clear()

    totals = {"taxable": Decimal("0"), "cgst": Decimal("0"), "sgst": Decimal("0"), "igst": Decimal("0")}
    for idx, line in enumerate(data.items):
        item = db.get(Item, line.item_id)
        if item is None or not item.is_active:
            raise BusinessRuleError(f"Line {idx + 1}: item {line.item_id} not found or inactive")
        if item.item_type not in STOCKABLE_PURCHASE_TYPES:
            raise BusinessRuleError(f"Line {idx + 1}: {item.code} is a finished good and cannot be purchased")
        unit = get_unit(db, line.unit_code)
        base_qty = convert(db, line.quantity, unit, item.base_unit, item.id)

        taxable = dec.money(line.quantity * line.rate)
        if intra_state:
            cgst = sgst = dec.money(taxable * line.gst_rate / 200)  # each half rounded on its own
            igst = Decimal("0.00")
        else:
            cgst = sgst = Decimal("0.00")
            igst = dec.money(taxable * line.gst_rate / 100)
        tax = cgst + sgst + igst
        purchase.items.append(PurchaseItem(
            item_id=item.id, quantity=line.quantity, unit_id=unit.id, base_quantity=base_qty, rate=line.rate,
            taxable_amount=taxable, gst_rate=line.gst_rate, tax_amount=tax, line_total=taxable + tax,
        ))
        totals["taxable"] += taxable
        totals["cgst"] += cgst
        totals["sgst"] += sgst
        totals["igst"] += igst

    purchase.taxable_amount = totals["taxable"]
    purchase.cgst_amount = totals["cgst"]
    purchase.sgst_amount = totals["sgst"]
    purchase.igst_amount = totals["igst"]
    purchase.total_amount = totals["taxable"] + totals["cgst"] + totals["sgst"] + totals["igst"]


def create_purchase(db: Session, data: PurchaseIn, actor: User, ip: str | None = None) -> Purchase:
    purchase = Purchase(status=DocumentStatus.DRAFT, created_by=actor.id, items=[])
    _apply(db, purchase, data)
    purchase.purchase_no = numbering.next_number(db, DocumentType.PURCHASE, data.received_date).number
    db.add(purchase)
    db.flush()
    audit.record(db, user_id=actor.id, action="CREATE", entity_type="purchase", entity_id=purchase.id,
                 after=audit.snapshot(purchase), summary=f"Purchase {purchase.purchase_no} drafted", ip=ip)
    return purchase


def update_purchase(db: Session, purchase_id: int, data: PurchaseIn, actor: User, ip: str | None = None) -> Purchase:
    purchase = _get(db, purchase_id, lock=True)
    if purchase.status != DocumentStatus.DRAFT:
        raise BusinessRuleError(f"Purchase {purchase.purchase_no} is {purchase.status.value}; only drafts can be edited")
    before = audit.snapshot(purchase)
    _apply(db, purchase, data)
    db.flush()
    audit.record_update(db, user_id=actor.id, entity_type="purchase", entity_id=purchase.id,
                        before=before, after=audit.snapshot(purchase), ip=ip)
    return purchase


def post_purchase(db: Session, purchase_id: int, actor: User, ip: str | None = None) -> Purchase:
    """Receive the goods: one PURCHASE_RECEIPT movement per line, all-or-nothing."""
    purchase = _get(db, purchase_id, lock=True)
    if purchase.status == DocumentStatus.POSTED:
        raise ConflictError(f"Purchase {purchase.purchase_no} is already posted")
    if purchase.status != DocumentStatus.DRAFT:
        raise BusinessRuleError(f"Purchase {purchase.purchase_no} is {purchase.status.value} and cannot be posted")
    supplier = db.get(Supplier, purchase.supplier_id)
    for line in purchase.items:
        post_movement(
            db, item_id=line.item_id, movement_type=MovementType.PURCHASE_RECEIPT, quantity=line.quantity,
            unit=get_unit(db, line.unit_id), total_value=line.taxable_amount, actor_id=actor.id,
            source_document_type="PURCHASE", source_document_id=purchase.id, reference_no=purchase.purchase_no,
            posting_key=f"PUR:{purchase.id}:LINE:{line.id}", movement_date=purchase.received_date,
            remarks=f"{supplier.name} bill {purchase.supplier_invoice_no}",
        )
    purchase.status = DocumentStatus.POSTED
    purchase.posted_by = actor.id
    purchase.posted_at = datetime.now(UTC)
    db.flush()
    audit.record(db, user_id=actor.id, action="POST", entity_type="purchase", entity_id=purchase.id,
                 summary=f"Purchase {purchase.purchase_no} posted to stock ({len(purchase.items)} lines)", ip=ip)
    return purchase


def cancel_purchase(db: Session, purchase_id: int, reason: str, actor: User, ip: str | None = None) -> Purchase:
    purchase = _get(db, purchase_id, lock=True)
    if purchase.status == DocumentStatus.POSTED:
        raise BusinessRuleError("A posted purchase cannot be cancelled; return the goods with a purchase return")
    if purchase.status == DocumentStatus.CANCELLED:
        raise ConflictError(f"Purchase {purchase.purchase_no} is already cancelled")
    purchase.status = DocumentStatus.CANCELLED
    db.flush()
    audit.record(db, user_id=actor.id, action="CANCEL", entity_type="purchase", entity_id=purchase.id,
                 reason=reason, summary=f"Purchase {purchase.purchase_no} cancelled", ip=ip)
    return purchase


def list_purchases(db: Session, *, supplier_id=None, status=None, date_from=None, date_to=None,
                   q=None, limit: int = 50, offset: int = 0):
    stmt = select(Purchase).order_by(Purchase.received_date.desc(), Purchase.id.desc())
    if supplier_id is not None:
        stmt = stmt.where(Purchase.supplier_id == supplier_id)
    if status is not None:
        stmt = stmt.where(Purchase.status == status)
    if date_from is not None:
        stmt = stmt.where(Purchase.received_date >= date_from)
    if date_to is not None:
        stmt = stmt.where(Purchase.received_date <= date_to)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Purchase.purchase_no.ilike(like) | Purchase.supplier_invoice_no.ilike(like))
    return paginate(db, stmt, limit, offset)
