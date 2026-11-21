"""Invoices (+PDF), credit notes, dispatches, payments and receivables. Writes: admin only."""
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import DbSession, client_ip, require_roles
from app.models import CreditNote, Customer, Dispatch, Invoice, Payment, SalesOrder, State, Unit, User
from app.models.enums import InvoiceStatus, RoleCode
from app.reports.amount_words import rupees_in_words
from app.reports.invoice_pdf import render_invoice_pdf
from app.schemas.billing import (
    AllocationOut,
    CreditNoteCreate,
    CreditNoteLineOut,
    CreditNoteOut,
    DispatchCreate,
    DispatchLineOut,
    DispatchOut,
    InvoiceCreate,
    InvoiceLineOut,
    InvoiceOut,
    InvoiceSummaryOut,
    OpenInvoiceOut,
    PaymentCreate,
    PaymentReallocateIn,
    PaymentReverseIn,
    PaymentOut,
    ReceivableOut,
)
from app.schemas.common import Page
from app.services import credit_notes as cn_svc
from app.services import dispatch as dsp_svc
from app.services import invoicing as inv_svc
from app.services import payments as pay_svc

Reader = Annotated[User, Depends(require_roles(RoleCode.ADMIN, RoleCode.OWNER, RoleCode.AUDITOR))]
Admin = Annotated[User, Depends(require_roles(RoleCode.ADMIN))]

invoices = APIRouter(prefix="/invoices", tags=["invoices"])
dispatches = APIRouter(prefix="/dispatches", tags=["dispatch"])
payments = APIRouter(prefix="/payments", tags=["payments"])
receivables = APIRouter(prefix="/receivables", tags=["payments"])


# ---- builders ----------------------------------------------------------------------------
def invoice_out(db: Session, inv: Invoice) -> InvoiceOut:
    units = {u.id: u.code for u in db.scalars(select(Unit))}
    credited, paid = inv_svc.credited_amount(db, inv.id), inv_svc.allocated_amount(db, inv.id)
    return InvoiceOut(
        id=inv.id, invoice_no=inv.invoice_no, financial_year=inv.financial_year, invoice_date=inv.invoice_date,
        order_id=inv.order_id, order_no=db.get(SalesOrder, inv.order_id).order_no, customer_id=inv.customer_id,
        customer_name=inv.customer_name, customer_gstin=inv.customer_gstin, billing_address=inv.billing_address,
        place_of_supply_state_code=inv.place_of_supply_state_code,
        place_of_supply=db.get(State, inv.place_of_supply_state_code).name,
        supplier_state_code=inv.supplier_state_code, supply_type=inv.supply_type, taxable_amount=inv.taxable_amount,
        cgst_amount=inv.cgst_amount, sgst_amount=inv.sgst_amount, igst_amount=inv.igst_amount,
        round_off=inv.round_off, total_amount=inv.total_amount, credited_amount=credited, paid_amount=paid,
        balance=inv_svc.invoice_balance(db, inv), status=inv.status,
        amount_in_words=rupees_in_words(inv.total_amount),
        items=[InvoiceLineOut(
            id=i.id, order_item_id=i.order_item_id, product_id=i.product_id, description=i.description,
            hsn_code=i.hsn_code, quantity=i.quantity, unit_code=units[i.unit_id], unit_price=i.unit_price,
            taxable_amount=i.taxable_amount, gst_rate=i.gst_rate, cgst_rate=i.cgst_rate, cgst_amount=i.cgst_amount,
            sgst_rate=i.sgst_rate, sgst_amount=i.sgst_amount, igst_rate=i.igst_rate, igst_amount=i.igst_amount,
            line_total=i.line_total) for i in inv.items],
    )


def credit_out(cn: CreditNote) -> CreditNoteOut:
    return CreditNoteOut(
        id=cn.id, credit_note_no=cn.credit_note_no, credit_note_date=cn.credit_note_date, invoice_id=cn.invoice_id,
        customer_id=cn.customer_id, reason_type=cn.reason_type, reason=cn.reason, restock=cn.restock,
        taxable_amount=cn.taxable_amount, cgst_amount=cn.cgst_amount, sgst_amount=cn.sgst_amount,
        igst_amount=cn.igst_amount, total_amount=cn.total_amount,
        items=[CreditNoteLineOut(invoice_item_id=i.invoice_item_id, product_id=i.product_id, quantity=i.quantity,
                                 taxable_amount=i.taxable_amount, cgst_amount=i.cgst_amount, sgst_amount=i.sgst_amount,
                                 igst_amount=i.igst_amount, line_total=i.line_total) for i in cn.items],
    )


def dispatch_out(d: Dispatch) -> DispatchOut:
    return DispatchOut(id=d.id, dispatch_no=d.dispatch_no, order_id=d.order_id, invoice_id=d.invoice_id,
                       dispatch_date=d.dispatch_date, vehicle_no=d.vehicle_no, transporter=d.transporter,
                       remarks=d.remarks, items=[DispatchLineOut(order_item_id=i.order_item_id,
                                                                 product_id=i.product_id, quantity=i.quantity)
                                                 for i in d.items])


def payment_out(db: Session, p: Payment) -> PaymentOut:
    return PaymentOut(
        id=p.id, receipt_no=p.receipt_no, customer_id=p.customer_id, customer_name=db.get(Customer, p.customer_id).name,
        payment_date=p.payment_date, amount=p.amount, mode=p.mode, reference_no=p.reference_no, remarks=p.remarks,
        unallocated=pay_svc.unallocated(db, p),
        reversed_on=p.reversed_on, reversal_reason=p.reversal_reason, reversed_by=p.reversed_by,
        allocations=[AllocationOut(invoice_id=a.invoice_id, invoice_no=db.get(Invoice, a.invoice_id).invoice_no,
                                   amount=a.amount) for a in p.allocations],
    )


# ---- invoices ----------------------------------------------------------------------------
@invoices.get("", response_model=Page[InvoiceSummaryOut])
def list_invoices(
    db: DbSession, _: Reader, customer_id: int | None = None, order_id: int | None = None,
    status_: Annotated[InvoiceStatus | None, Query(alias="status")] = None,
    date_from: date | None = None, date_to: date | None = None, q: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50, offset: Annotated[int, Query(ge=0)] = 0,
):
    rows, total = inv_svc.list_invoices(db, customer_id=customer_id, order_id=order_id, status=status_, date_from=date_from,
                                        date_to=date_to, q=q, limit=limit, offset=offset)
    items = [InvoiceSummaryOut(id=i.id, invoice_no=i.invoice_no, invoice_date=i.invoice_date, customer_id=i.customer_id,
                               customer_name=i.customer_name, supply_type=i.supply_type, taxable_amount=i.taxable_amount,
                               total_amount=i.total_amount, balance=inv_svc.invoice_balance(db, i), status=i.status)
             for i in rows]
    return Page(items=items, total=total, limit=limit, offset=offset)


@invoices.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, db: DbSession, _: Reader):
    return invoice_out(db, inv_svc.get_invoice(db, invoice_id))


@invoices.get("/{invoice_id}/pdf", response_class=Response,
              responses={200: {"content": {"application/pdf": {}}}})
def invoice_pdf(invoice_id: int, db: DbSession, _: Reader):
    inv = inv_svc.get_invoice(db, invoice_id)
    filename = inv.invoice_no.replace("/", "-") + ".pdf"
    return Response(render_invoice_pdf(db, inv), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@invoices.post("", response_model=InvoiceOut, status_code=status.HTTP_201_CREATED)
def create_invoice(data: InvoiceCreate, db: DbSession, actor: Admin, request: Request):
    return invoice_out(db, inv_svc.create_invoice(db, data.order_id, data.invoice_date, actor, client_ip(request)))


@invoices.get("/{invoice_id}/credit-notes", response_model=list[CreditNoteOut])
def list_credit_notes(invoice_id: int, db: DbSession, _: Reader):
    inv_svc.get_invoice(db, invoice_id)
    return [credit_out(cn) for cn in db.scalars(select(CreditNote).where(CreditNote.invoice_id == invoice_id)
                                                .order_by(CreditNote.id))]


@invoices.post("/{invoice_id}/credit-notes", response_model=CreditNoteOut, status_code=status.HTTP_201_CREATED)
def create_credit_note(invoice_id: int, data: CreditNoteCreate, db: DbSession, actor: Admin, request: Request):
    """Cancel (full), sales return or price adjustment. Invoices are never deleted."""
    cn = cn_svc.create_credit_note(
        db, invoice_id=invoice_id, reason_type=data.reason_type, reason=data.reason, restock=data.restock,
        lines=[cn_svc.CreditLineIn(line.invoice_item_id, line.quantity, line.taxable_amount) for line in data.lines],
        credit_date=data.credit_note_date, actor=actor, ip=client_ip(request))
    return credit_out(cn)


# ---- dispatches --------------------------------------------------------------------------
@dispatches.get("", response_model=Page[DispatchOut])
def list_dispatches(db: DbSession, _: Reader, order_id: int | None = None, date_from: date | None = None,
                    date_to: date | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                    offset: Annotated[int, Query(ge=0)] = 0):
    rows, total = dsp_svc.list_dispatches(db, order_id=order_id, date_from=date_from, date_to=date_to,
                                          limit=limit, offset=offset)
    return Page(items=[dispatch_out(d) for d in rows], total=total, limit=limit, offset=offset)


@dispatches.get("/{dispatch_id}", response_model=DispatchOut)
def get_dispatch(dispatch_id: int, db: DbSession, _: Reader):
    return dispatch_out(dsp_svc.get_dispatch(db, dispatch_id))


@dispatches.post("", response_model=DispatchOut, status_code=status.HTTP_201_CREATED)
def create_dispatch(data: DispatchCreate, db: DbSession, actor: Admin, request: Request):
    lines = {i.order_item_id: i.quantity for i in data.items} if data.items else None
    return dispatch_out(dsp_svc.create_dispatch(
        db, order_id=data.order_id, lines=lines, dispatch_date=data.dispatch_date, vehicle_no=data.vehicle_no,
        transporter=data.transporter, remarks=data.remarks, actor=actor, ip=client_ip(request)))


# ---- payments & receivables --------------------------------------------------------------
@payments.get("", response_model=Page[PaymentOut])
def list_payments(db: DbSession, _: Reader, customer_id: int | None = None, date_from: date | None = None,
                  date_to: date | None = None, limit: Annotated[int, Query(ge=1, le=200)] = 50,
                  offset: Annotated[int, Query(ge=0)] = 0):
    rows, total = pay_svc.list_payments(db, customer_id=customer_id, date_from=date_from, date_to=date_to,
                                        limit=limit, offset=offset)
    return Page(items=[payment_out(db, p) for p in rows], total=total, limit=limit, offset=offset)


@payments.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def record_payment(data: PaymentCreate, db: DbSession, actor: Admin, request: Request):
    allocations = [(a.invoice_id, a.amount) for a in data.allocations] if data.allocations is not None else None
    p = pay_svc.record_payment(
        db, customer_id=data.customer_id, payment_date=data.payment_date or date.today(), amount=data.amount,
        mode=data.mode, reference_no=data.reference_no, remarks=data.remarks, allocations=allocations,
        actor=actor, ip=client_ip(request))
    return payment_out(db, p)


@payments.post("/{payment_id}/reallocate", response_model=PaymentOut)
def reallocate_payment(payment_id: int, data: PaymentReallocateIn, db: DbSession, actor: Admin, request: Request):
    """Move a receipt to different invoices of the same customer; the rest stays as an advance."""
    return payment_out(db, pay_svc.reallocate_payment(
        db, payment_id, allocations=[(a.invoice_id, a.amount) for a in data.allocations], reason=data.reason,
        actor=actor, ip=client_ip(request)))


@payments.post("/{payment_id}/reverse", response_model=PaymentOut)
def reverse_payment(payment_id: int, data: PaymentReverseIn, db: DbSession, actor: Admin, request: Request):
    """Reverse a receipt (bounced cheque, failed transfer). The invoices it paid become due again."""
    return payment_out(db, pay_svc.reverse_payment(db, payment_id, reason=data.reason, reversal_date=data.reversal_date,
                                                    actor=actor, ip=client_ip(request)))


@receivables.get("", response_model=list[ReceivableOut])
def outstanding(db: DbSession, _: Reader, as_of: date | None = None, customer_id: int | None = None):
    """Customer outstanding with ageing buckets (days since invoice date)."""
    return [ReceivableOut(
        customer_id=r.customer.id, customer_code=r.customer.code, customer_name=r.customer.name,
        invoiced=r.invoiced, credited=r.credited, received=r.received, invoice_outstanding=r.invoice_outstanding,
        unallocated_advance=r.unallocated, outstanding=r.outstanding, ageing=r.buckets,
        open_invoices=[OpenInvoiceOut(invoice_id=i.id, invoice_no=i.invoice_no, invoice_date=i.invoice_date,
                                      total_amount=i.total_amount, balance=bal, age_days=days)
                       for i, bal, days in r.open_invoices],
    ) for r in pay_svc.receivables(db, as_of, customer_id)]
