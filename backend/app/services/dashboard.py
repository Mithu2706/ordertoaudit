"""Owner / admin dashboard: every figure is computed live from documents and the ledger.

Windows: sales, collections and top customers = current calendar month;
production efficiency = last 30 days (so a run early in the month is never "missing");
sales trend = last 30 days, one point per day.
"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.models import CreditNote, Invoice, Item, Payment, ProductionRun, SalesOrder
from app.models.enums import DocumentStatus, ItemType, OrderStatus
from app.services.availability import check_order
from app.services.costing import run_costing
from app.services.inventory import balances
from app.services.payments import receivables

ZERO = Decimal("0")


def _s(v: Decimal | None) -> str | None:
    return None if v is None else f"{v:f}"


def owner_dashboard(db: Session, today: date | None = None) -> dict:
    today = today or date.today()
    month_start = today.replace(day=1)
    window_start = today - timedelta(days=29)

    month_invoices = db.scalars(select(Invoice).where(Invoice.invoice_date.between(month_start, today))).all()
    gross_taxable = sum((i.taxable_amount for i in month_invoices), ZERO)
    gross_total = sum((i.total_amount for i in month_invoices), ZERO)
    credited = Decimal(db.scalar(select(func.coalesce(func.sum(CreditNote.taxable_amount), 0))
                                 .where(CreditNote.credit_note_date.between(month_start, today))) or 0)
    collected = Decimal(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))
                                  .where(Payment.payment_date.between(month_start, today))) or 0)
    recv = receivables(db, today)
    outstanding = sum((r.outstanding for r in recv), ZERO)
    overdue = sum((amt for r in recv for label, amt in r.buckets.items() if not label.startswith("0-")), ZERO)

    # Orders pipeline
    counts = dict(db.execute(select(SalesOrder.status, func.count()).group_by(SalesOrder.status)).all())
    submitted = db.scalars(select(SalesOrder).where(SalesOrder.status == OrderStatus.SUBMITTED)).all()
    short = sum(1 for o in submitted if any(not c.can_fulfil for c in check_order(db, o)))

    # Stock
    stock_rows = balances(db)
    value_by_type = defaultdict(lambda: ZERO)
    for r in stock_rows:
        value_by_type[r.item.item_type.value] += r.value
    low = [{"item_id": r.item.id, "code": r.item.code, "name": r.item.name, "unit": r.item.base_unit.code,
            "quantity": _s(r.quantity), "reorder_level": _s(r.item.reorder_level)}
           for r in stock_rows if r.low_stock]

    # Production (last 30 days)
    runs = db.scalars(select(ProductionRun).where(ProductionRun.status == DocumentStatus.POSTED,
                                                  ProductionRun.production_date.between(window_start, today))
                      .order_by(ProductionRun.production_date.desc(), ProductionRun.id.desc())).all()
    expected = sum((r.expected_output for r in runs), ZERO)
    good = sum((r.actual_good_output for r in runs), ZERO)
    latest = run_costing(db, runs[0]) if runs else None

    # Sales trend (last 30 days)
    daily = defaultdict(lambda: ZERO)
    for inv in db.scalars(select(Invoice).where(Invoice.invoice_date.between(window_start, today))):
        daily[inv.invoice_date] += inv.taxable_amount
    trend = [{"date": (window_start + timedelta(days=i)).isoformat(),
              "taxable": _s(daily[window_start + timedelta(days=i)])} for i in range(30)]

    by_customer = defaultdict(lambda: ZERO)
    names = {}
    for inv in month_invoices:
        by_customer[inv.customer_id] += inv.total_amount
        names[inv.customer_id] = inv.customer_name
    top = sorted(by_customer.items(), key=lambda kv: kv[1], reverse=True)[:5]

    return {
        "as_of": today.isoformat(),
        "month": {"from": month_start.isoformat(), "to": today.isoformat()},
        "sales": {"invoices": len(month_invoices), "gross_taxable": _s(gross_taxable), "gross_total": _s(gross_total),
                  "credited_taxable": _s(credited), "net_taxable": _s(gross_taxable - credited)},
        "collections": {"month": _s(collected)},
        "receivables": {"outstanding": _s(outstanding), "overdue": _s(overdue),
                        "customers": [{"customer_id": r.customer.id, "name": r.customer.name,
                                       "outstanding": _s(r.outstanding)} for r in recv if r.outstanding != 0]},
        "orders": {"pending_approval": counts.get(OrderStatus.SUBMITTED, 0), "pending_with_shortage": short,
                   "awaiting_invoice": counts.get(OrderStatus.APPROVED, 0),
                   "awaiting_dispatch": counts.get(OrderStatus.INVOICED, 0) + counts.get(OrderStatus.PARTIALLY_DISPATCHED, 0)},
        "stock": {"value_by_type": {t.value: _s(value_by_type[t.value]) for t in ItemType},
                  "total_value": _s(sum(value_by_type.values(), ZERO)), "low_stock": low},
        "production": {
            "runs": len(runs), "expected": _s(expected), "good": _s(good),
            "yield_pct": _s(dec.pct(good / expected * 100)) if expected else None,
            "alerts": sum(1 for r in runs if r.has_variance_alert),
            "latest": None if not runs else {
                "run_id": runs[0].id, "run_no": runs[0].run_no, "product": db.get(Item, runs[0].product_id).name,
                "cost_per_unit": _s(latest.cost_per_unit), "margin_pct": _s(latest.margin_pct),
                "yield_variance_pct": _s(runs[0].yield_variance_pct)},
        },
        "sales_trend": trend,
        "top_customers": [{"customer_id": cid, "name": names[cid], "total": _s(v)} for cid, v in top],
    }
