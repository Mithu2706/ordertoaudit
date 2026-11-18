from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import MATERIAL_READERS, DbSession, client_ip, require_roles
from app.models import Item, Purchase, Supplier, Unit, User
from app.models.enums import DocumentStatus, RoleCode
from app.schemas.common import Page
from app.schemas.purchases import PurchaseIn, PurchaseLineOut, PurchaseOut, PurchaseSummaryOut
from app.services import purchases as svc

router = APIRouter(prefix="/purchases", tags=["purchases"])
Reader = Annotated[User, Depends(require_roles(*MATERIAL_READERS))]
Writer = Annotated[User, Depends(require_roles(RoleCode.ADMIN, RoleCode.PRODUCTION))]


def purchase_out(db: Session, p: Purchase) -> PurchaseOut:
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    items = {i.id: i for i in db.scalars(select(Item).where(Item.id.in_([li.item_id for li in p.items])))}
    return PurchaseOut(
        id=p.id, purchase_no=p.purchase_no, supplier_id=p.supplier_id, supplier_name=db.get(Supplier, p.supplier_id).name,
        supplier_invoice_no=p.supplier_invoice_no, supplier_invoice_date=p.supplier_invoice_date,
        received_date=p.received_date, status=p.status, taxable_amount=p.taxable_amount, cgst_amount=p.cgst_amount,
        sgst_amount=p.sgst_amount, igst_amount=p.igst_amount, total_amount=p.total_amount, notes=p.notes,
        created_by=p.created_by, posted_by=p.posted_by, posted_at=p.posted_at,
        items=[
            PurchaseLineOut(
                id=li.id, item_id=li.item_id, item_code=items[li.item_id].code, item_name=items[li.item_id].name,
                quantity=li.quantity, unit_code=units[li.unit_id], base_quantity=li.base_quantity,
                base_unit_code=units[items[li.item_id].base_unit_id], rate=li.rate, taxable_amount=li.taxable_amount,
                gst_rate=li.gst_rate, tax_amount=li.tax_amount, line_total=li.line_total,
            )
            for li in p.items
        ],
    )


@router.get("", response_model=Page[PurchaseSummaryOut])
def list_purchases(
    db: DbSession, _: Reader,
    supplier_id: int | None = None,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = svc.list_purchases(db, supplier_id=supplier_id, status=status_, date_from=date_from,
                                     date_to=date_to, q=q, limit=limit, offset=offset)
    return Page(items=rows, total=total, limit=limit, offset=offset)


@router.get("/{purchase_id}", response_model=PurchaseOut)
def get_purchase(purchase_id: int, db: DbSession, _: Reader):
    return purchase_out(db, svc.get_purchase(db, purchase_id))


@router.post("", response_model=PurchaseOut, status_code=status.HTTP_201_CREATED)
def create_purchase(data: PurchaseIn, db: DbSession, actor: Writer, request: Request):
    return purchase_out(db, svc.create_purchase(db, data, actor, client_ip(request)))


@router.put("/{purchase_id}", response_model=PurchaseOut)
def update_purchase(purchase_id: int, data: PurchaseIn, db: DbSession, actor: Writer, request: Request):
    return purchase_out(db, svc.update_purchase(db, purchase_id, data, actor, client_ip(request)))


@router.post("/{purchase_id}/post", response_model=PurchaseOut)
def post_purchase(purchase_id: int, db: DbSession, actor: Writer, request: Request):
    """Receive the goods into stock. All lines post together or none do."""
    return purchase_out(db, svc.post_purchase(db, purchase_id, actor, client_ip(request)))


@router.post("/{purchase_id}/cancel", response_model=PurchaseOut)
def cancel_purchase(purchase_id: int, db: DbSession, actor: Writer, request: Request,
                    reason: Annotated[str, Body(embed=True, min_length=3, max_length=255)]):
    return purchase_out(db, svc.cancel_purchase(db, purchase_id, reason, actor, client_ip(request)))
