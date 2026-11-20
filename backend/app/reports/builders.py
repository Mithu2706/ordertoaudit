"""All reports. Each reads posted/issued documents and the stock ledger only (no
hard-coded figures), filtered by the period [date_from, date_to]."""
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from app.core import decimals as dec
from app.models import (
    CreditNote,
    CreditNoteItem,
    Customer,
    Invoice,
    InvoiceItem,
    Item,
    Payment,
    ProductionConsumption,
    ProductionRun,
    Purchase,
    State,
    StockMovement,
    Supplier,
    Unit,
)
from app.models.enums import DocumentStatus, ItemType, RoleCode
from app.reports.framework import Column, Kind, Params, Report, report
from app.services.costing import run_costing
from app.services.payments import bucket_labels, receivables
from app.services.reference import get_setting

R = RoleCode
FINANCE = (R.ADMIN, R.OWNER, R.AUDITOR)
OPERATIONS = (R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR)
ZERO = Decimal("0")
C = Column


def _period(p: Params, **extra) -> dict[str, str]:
    return {"Period": f"{p.date_from:%d-%m-%Y} to {p.date_to:%d-%m-%Y}", **{k: str(v) for k, v in extra.items()}}


def _units(db: Session) -> dict[int, str]:
    return {u.id: u.code for u in db.scalars(select(Unit))}


def _invoices(db: Session, p: Params):
    stmt = select(Invoice).where(Invoice.invoice_date.between(p.date_from, p.date_to))
    if p.customer_id:
        stmt = stmt.where(Invoice.customer_id == p.customer_id)
    return db.scalars(stmt.order_by(Invoice.invoice_date, Invoice.id)).all()


# ---- sales ------------------------------------------------------------------------------
@report("sales-register", "Sales register", roles=FINANCE, params=("customer_id",),
        description="Every GST invoice in the period with its tax split.")
def sales_register(db: Session, p: Params) -> Report:
    rows = [{
        "invoice_no": i.invoice_no, "invoice_date": i.invoice_date, "customer": i.customer_name,
        "gstin": i.customer_gstin or "Unregistered", "place_of_supply": i.place_of_supply_state_code,
        "supply_type": i.supply_type.value.replace("_", "-").title(), "taxable": i.taxable_amount,
        "cgst": i.cgst_amount, "sgst": i.sgst_amount, "igst": i.igst_amount, "total": i.total_amount,
        "status": i.status.value,
    } for i in _invoices(db, p)]
    return Report("sales-register", "Sales register", [
        C("invoice_no", "Invoice no"), C("invoice_date", "Date", Kind.DATE), C("customer", "Customer"),
        C("gstin", "GSTIN"), C("place_of_supply", "POS"), C("supply_type", "Supply"),
        C("taxable", "Taxable", Kind.MONEY, True), C("cgst", "CGST", Kind.MONEY, True),
        C("sgst", "SGST", Kind.MONEY, True), C("igst", "IGST", Kind.MONEY, True),
        C("total", "Invoice total", Kind.MONEY, True), C("status", "Status"),
    ], rows, _period(p), ["Cancelled invoices stay in the register; their reversal appears in the GST summary "
                          "as credit notes."])


@report("customer-sales", "Customer-wise sales", roles=(*FINANCE, R.SALESMAN), params=("customer_id",),
        description="Invoiced, credited and net sales per customer (salesmen see their own customers).")
def customer_sales(db: Session, p: Params) -> Report:
    agg: dict[int, dict] = {}
    for i in _invoices(db, p):
        a = agg.setdefault(i.customer_id, {"invoices": 0, "taxable": ZERO, "tax": ZERO, "total": ZERO, "credited": ZERO})
        a["invoices"] += 1
        a["taxable"] += i.taxable_amount
        a["tax"] += i.cgst_amount + i.sgst_amount + i.igst_amount
        a["total"] += i.total_amount
    cn_stmt = select(CreditNote).where(CreditNote.credit_note_date.between(p.date_from, p.date_to))
    for cn in db.scalars(cn_stmt):
        if cn.customer_id in agg:
            agg[cn.customer_id]["credited"] += cn.total_amount
    rows = []
    for cid, a in agg.items():
        cust = db.get(Customer, cid)
        if p.actor and p.actor.role.code == R.SALESMAN and cust.assigned_salesman_id != p.actor.id:
            continue  # salesmen only see their own customers
        rows.append({"code": cust.code, "customer": cust.name, "state": cust.state_code, "invoices": a["invoices"],
                     "taxable": a["taxable"], "tax": a["tax"], "total": a["total"], "credited": a["credited"],
                     "net": a["total"] - a["credited"]})
    rows.sort(key=lambda r: r["net"], reverse=True)
    return Report("customer-sales", "Customer-wise sales", [
        C("code", "Code"), C("customer", "Customer"), C("state", "State"), C("invoices", "Invoices", Kind.INT, True),
        C("taxable", "Taxable", Kind.MONEY, True), C("tax", "GST", Kind.MONEY, True),
        C("total", "Invoiced", Kind.MONEY, True), C("credited", "Credit notes", Kind.MONEY, True),
        C("net", "Net sales", Kind.MONEY, True),
    ], rows, _period(p))


@report("product-sales", "Product-wise sales", roles=FINANCE, params=("product_id",),
        description="Quantity and value invoiced per product.")
def product_sales(db: Session, p: Params) -> Report:
    stmt = (select(InvoiceItem, Invoice).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
            .where(Invoice.invoice_date.between(p.date_from, p.date_to)))
    if p.product_id:
        stmt = stmt.where(InvoiceItem.product_id == p.product_id)
    agg: dict[int, dict] = {}
    units = _units(db)
    for it, _inv in db.execute(stmt):
        a = agg.setdefault(it.product_id, {"qty": ZERO, "taxable": ZERO, "tax": ZERO, "total": ZERO,
                                           "hsn": it.hsn_code, "unit": units[it.unit_id]})
        a["qty"] += it.quantity
        a["taxable"] += it.taxable_amount
        a["tax"] += it.cgst_amount + it.sgst_amount + it.igst_amount
        a["total"] += it.line_total
    rows = []
    for pid, a in agg.items():
        item = db.get(Item, pid)
        rows.append({"code": item.code, "product": item.name, "hsn": a["hsn"], "qty": a["qty"], "unit": a["unit"],
                     "avg_rate": dec.money(a["taxable"] / a["qty"]) if a["qty"] else None,
                     "taxable": a["taxable"], "tax": a["tax"], "total": a["total"]})
    return Report("product-sales", "Product-wise sales", [
        C("code", "Code"), C("product", "Product"), C("hsn", "HSN"), C("qty", "Quantity", Kind.QTY, True),
        C("unit", "Unit"), C("avg_rate", "Avg rate", Kind.MONEY), C("taxable", "Taxable", Kind.MONEY, True),
        C("tax", "GST", Kind.MONEY, True), C("total", "Total", Kind.MONEY, True),
    ], rows, _period(p), ["Gross of credit notes (see the GST summary for net figures)."])


@report("gst-summary", "GST outward supply summary", roles=FINANCE,
        description="Outward supplies by place of supply, supply type, HSN and rate, net of credit notes.")
def gst_summary(db: Session, p: Params) -> Report:
    states = {s.code: s.name for s in db.scalars(select(State))}
    agg: dict[tuple, dict] = defaultdict(lambda: {"docs": set(), "taxable": ZERO, "cgst": ZERO, "sgst": ZERO, "igst": ZERO})
    inv_rows = db.execute(select(InvoiceItem, Invoice).join(Invoice, Invoice.id == InvoiceItem.invoice_id)
                          .where(Invoice.invoice_date.between(p.date_from, p.date_to)))
    for it, inv in inv_rows:
        a = agg[("Invoices", inv.place_of_supply_state_code, inv.supply_type.value, it.hsn_code, it.gst_rate)]
        a["docs"].add(inv.id)
        a["taxable"] += it.taxable_amount
        a["cgst"] += it.cgst_amount
        a["sgst"] += it.sgst_amount
        a["igst"] += it.igst_amount
    cn_rows = db.execute(
        select(CreditNoteItem, CreditNote, InvoiceItem, Invoice)
        .join(CreditNote, CreditNote.id == CreditNoteItem.credit_note_id)
        .join(InvoiceItem, InvoiceItem.id == CreditNoteItem.invoice_item_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(CreditNote.credit_note_date.between(p.date_from, p.date_to)))
    for ci, cn, it, inv in cn_rows:
        a = agg[("Credit notes", inv.place_of_supply_state_code, inv.supply_type.value, it.hsn_code, it.gst_rate)]
        a["docs"].add(cn.id)
        a["taxable"] -= ci.taxable_amount
        a["cgst"] -= ci.cgst_amount
        a["sgst"] -= ci.sgst_amount
        a["igst"] -= ci.igst_amount
    rows = [{
        "document": k[0], "place_of_supply": f"{k[1]} {states.get(k[1], '')}", "supply_type": k[2].replace("_", "-").title(),
        "hsn": k[3], "rate": k[4], "documents": len(a["docs"]), "taxable": a["taxable"], "cgst": a["cgst"],
        "sgst": a["sgst"], "igst": a["igst"], "total_tax": a["cgst"] + a["sgst"] + a["igst"],
    } for k, a in sorted(agg.items(), key=lambda kv: (kv[0][0] != "Invoices", kv[0][1], kv[0][3]))]
    return Report("gst-summary", "GST outward supply summary", [
        C("document", "Document"), C("place_of_supply", "Place of supply"), C("supply_type", "Supply"),
        C("hsn", "HSN"), C("rate", "GST %", Kind.PCT), C("documents", "Docs", Kind.INT),
        C("taxable", "Taxable", Kind.MONEY, True), C("cgst", "CGST", Kind.MONEY, True),
        C("sgst", "SGST", Kind.MONEY, True), C("igst", "IGST", Kind.MONEY, True),
        C("total_tax", "Total tax", Kind.MONEY, True),
    ], rows, _period(p), ["Credit notes are shown as negative amounts; the totals row is the net outward liability.",
                          f"Simplified exercise rate; GST rates come from the product master "
                          f"(default {get_setting(db, 'default_gst_rate')} %)."])


# ---- purchases --------------------------------------------------------------------------
@report("purchase-register", "Purchase register", roles=OPERATIONS,
        description="Posted purchase receipts with input GST.")
def purchase_register(db: Session, p: Params) -> Report:
    stmt = (select(Purchase).where(Purchase.status == DocumentStatus.POSTED,
                                   Purchase.received_date.between(p.date_from, p.date_to))
            .order_by(Purchase.received_date, Purchase.id))
    rows = []
    for pu in db.scalars(stmt):
        sup = db.get(Supplier, pu.supplier_id)
        rows.append({"purchase_no": pu.purchase_no, "received_date": pu.received_date, "supplier": sup.name,
                     "gstin": sup.gstin or "Unregistered", "bill_no": pu.supplier_invoice_no,
                     "bill_date": pu.supplier_invoice_date, "taxable": pu.taxable_amount, "cgst": pu.cgst_amount,
                     "sgst": pu.sgst_amount, "igst": pu.igst_amount, "total": pu.total_amount})
    return Report("purchase-register", "Purchase register", [
        C("purchase_no", "Purchase no"), C("received_date", "Received", Kind.DATE), C("supplier", "Supplier"),
        C("gstin", "GSTIN"), C("bill_no", "Supplier bill"), C("bill_date", "Bill date", Kind.DATE),
        C("taxable", "Taxable", Kind.MONEY, True), C("cgst", "CGST", Kind.MONEY, True),
        C("sgst", "SGST", Kind.MONEY, True), C("igst", "IGST", Kind.MONEY, True), C("total", "Total", Kind.MONEY, True),
    ], rows, _period(p), ["Stock is valued at the taxable amount; input GST is claimed as credit."])


# ---- stock ------------------------------------------------------------------------------
def _stock_summary(db: Session, p: Params, item_type: ItemType, key: str, title: str) -> Report:
    def latest_before(cond):
        sub = (select(StockMovement.item_id, func.max(StockMovement.id).label("mid")).where(cond)
               .group_by(StockMovement.item_id).subquery())
        return {iid: (q, v) for iid, q, v in db.execute(
            select(sub.c.item_id, StockMovement.balance_after, StockMovement.value_after)
            .join(StockMovement, StockMovement.id == sub.c.mid))}

    opening = latest_before(StockMovement.movement_date < p.date_from)
    closing = latest_before(StockMovement.movement_date <= p.date_to)
    flows = {iid: (qin, qout) for iid, qin, qout in db.execute(
        select(StockMovement.item_id,
               func.coalesce(func.sum(case((StockMovement.quantity > 0, StockMovement.quantity), else_=0)), 0),
               func.coalesce(func.sum(case((StockMovement.quantity < 0, -StockMovement.quantity), else_=0)), 0))
        .where(StockMovement.movement_date.between(p.date_from, p.date_to)).group_by(StockMovement.item_id))}
    units = _units(db)
    rows = []
    for item in db.scalars(select(Item).where(Item.item_type == item_type, Item.is_active).order_by(Item.name)):
        oq, ov = opening.get(item.id, (ZERO, ZERO))
        cq, cv = closing.get(item.id, (ZERO, ZERO))
        qin, qout = flows.get(item.id, (ZERO, ZERO))
        rows.append({
            "code": item.code, "item": item.name, "unit": units[item.base_unit_id], "opening": oq,
            "opening_value": ov, "received": Decimal(qin), "issued": Decimal(qout), "closing": cq,
            "avg_cost": dec.rate(cv / cq) if cq else None, "closing_value": cv, "reorder_level": item.reorder_level,
            "low_stock": item.reorder_level > 0 and cq <= item.reorder_level,
        })
    return Report(key, title, [
        C("code", "Code"), C("item", "Item"), C("unit", "Unit"), C("opening", "Opening", Kind.QTY),
        C("opening_value", "Opening value", Kind.MONEY, True), C("received", "In", Kind.QTY),
        C("issued", "Out", Kind.QTY), C("closing", "Closing", Kind.QTY), C("avg_cost", "Avg cost", Kind.RATE),
        C("closing_value", "Closing value", Kind.MONEY, True), C("reorder_level", "Reorder at", Kind.QTY),
        C("low_stock", "Low", Kind.BOOL),
    ], rows, _period(p), ["Derived from the stock ledger; valued at weighted-average cost."])


@report("raw-material-stock", "Raw-material stock", roles=OPERATIONS, description="Opening, in, out, closing and value.")
def raw_stock(db: Session, p: Params) -> Report:
    return _stock_summary(db, p, ItemType.RAW_MATERIAL, "raw-material-stock", "Raw-material stock")


@report("packaging-stock", "Packaging stock", roles=OPERATIONS, description="Opening, in, out, closing and value.")
def packaging_stock(db: Session, p: Params) -> Report:
    return _stock_summary(db, p, ItemType.PACKAGING, "packaging-stock", "Packaging stock")


@report("finished-goods-stock", "Finished-goods stock", roles=OPERATIONS, description="Opening, in, out, closing and value.")
def fg_stock(db: Session, p: Params) -> Report:
    return _stock_summary(db, p, ItemType.FINISHED_GOOD, "finished-goods-stock", "Finished-goods stock")


@report("stock-ledger", "Stock movement ledger", roles=OPERATIONS, params=("item_id",),
        description="Every stock movement with running balance (filter by item for a stock card).")
def stock_ledger(db: Session, p: Params) -> Report:
    stmt = (select(StockMovement, Item).join(Item, Item.id == StockMovement.item_id)
            .where(StockMovement.movement_date.between(p.date_from, p.date_to)))
    if p.item_id:
        stmt = stmt.where(StockMovement.item_id == p.item_id)
    units = _units(db)
    rows = [{
        "date": m.movement_date, "reference": m.reference_no, "item": item.code, "type": m.movement_type.value,
        "in": m.quantity if m.quantity > 0 else None, "out": -m.quantity if m.quantity < 0 else None,
        "unit": units[m.unit_id], "balance": m.balance_after, "unit_cost": m.unit_cost, "value": m.value,
        "value_after": m.value_after, "source": m.source_document_type, "remarks": m.remarks or "",
    } for m, item in db.execute(stmt.order_by(StockMovement.id))]
    filters = _period(p, Item=db.get(Item, p.item_id).code) if p.item_id else _period(p)
    return Report("stock-ledger", "Stock movement ledger", [
        C("date", "Date", Kind.DATE), C("reference", "Reference"), C("item", "Item"), C("type", "Movement"),
        C("in", "In", Kind.QTY), C("out", "Out", Kind.QTY), C("unit", "Unit"), C("balance", "Balance", Kind.QTY),
        C("unit_cost", "Unit cost", Kind.RATE), C("value", "Value", Kind.MONEY),
        C("value_after", "Stock value", Kind.MONEY), C("source", "Source"), C("remarks", "Remarks"),
    ], rows, filters)


# ---- production -------------------------------------------------------------------------
def _runs(db: Session, p: Params):
    stmt = select(ProductionRun).where(ProductionRun.status == DocumentStatus.POSTED,
                                       ProductionRun.production_date.between(p.date_from, p.date_to))
    if p.product_id:
        stmt = stmt.where(ProductionRun.product_id == p.product_id)
    return db.scalars(stmt.order_by(ProductionRun.production_date, ProductionRun.id)).all()


@report("production", "Production report", roles=OPERATIONS, params=("product_id",),
        description="Posted runs: output, yield variance and cost.")
def production_report(db: Session, p: Params) -> Report:
    rows = [{
        "run_no": r.run_no, "date": r.production_date, "product": db.get(Item, r.product_id).name,
        "expected": r.expected_output, "good": r.actual_good_output, "damaged": r.damaged_output,
        "yield_var": r.yield_variance_pct, "material": r.material_cost, "packaging": r.packaging_cost,
        "labour": r.labour_cost, "power_gas": r.power_gas_cost, "total": r.total_cost,
        "cost_per_unit": r.cost_per_good_unit, "alert": r.has_variance_alert,
    } for r in _runs(db, p)]
    return Report("production", "Production report", [
        C("run_no", "Run"), C("date", "Date", Kind.DATE), C("product", "Product"),
        C("expected", "Expected", Kind.QTY, True), C("good", "Good", Kind.QTY, True),
        C("damaged", "Damaged", Kind.QTY, True), C("yield_var", "Yield var %", Kind.PCT),
        C("material", "Material", Kind.MONEY, True), C("packaging", "Packaging", Kind.MONEY, True),
        C("labour", "Labour", Kind.MONEY, True), C("power_gas", "Gas & power", Kind.MONEY, True),
        C("total", "Total cost", Kind.MONEY, True), C("cost_per_unit", "Cost / unit", Kind.RATE),
        C("alert", "Alert", Kind.BOOL),
    ], rows, _period(p))


@report("consumption-variance", "Planned vs actual consumption", roles=OPERATIONS, params=("product_id",),
        description="Per run and component: planned, actual, damaged, variance % and alerts.")
def consumption_variance(db: Session, p: Params) -> Report:
    units = _units(db)
    rows = []
    for r in _runs(db, p):
        for c in sorted(r.consumption, key=lambda c: (c.component_type != ItemType.RAW_MATERIAL, c.id)):
            used = (c.actual_quantity or ZERO) + c.damaged_quantity
            rows.append({
                "run_no": r.run_no, "date": r.production_date, "component": db.get(Item, c.item_id).name,
                "type": "Raw" if c.component_type == ItemType.RAW_MATERIAL else "Packaging",
                "unit": units[c.unit_id], "planned": c.planned_quantity, "actual": c.actual_quantity,
                "damaged": c.damaged_quantity, "consumed": used, "variance_qty": used - c.planned_quantity,
                "variance_pct": c.variance_pct, "tolerance": r.variance_tolerance_pct, "alert": c.is_variance_alert,
                "cost": c.total_cost,
            })
    return Report("consumption-variance", "Planned vs actual consumption", [
        C("run_no", "Run"), C("date", "Date", Kind.DATE), C("component", "Component"), C("type", "Type"),
        C("unit", "Unit"), C("planned", "Planned", Kind.QTY), C("actual", "Used", Kind.QTY),
        C("damaged", "Damaged", Kind.QTY), C("consumed", "Total", Kind.QTY), C("variance_qty", "Var qty", Kind.QTY),
        C("variance_pct", "Var %", Kind.PCT), C("tolerance", "Tol %", Kind.PCT), C("alert", "Alert", Kind.BOOL),
        C("cost", "Cost", Kind.MONEY, True),
    ], rows, _period(p), ["Variance % = (actual + damaged - planned) / planned x 100. Packaging is planned per "
                          "good packet (cartons rounded down to full cartons)."])


@report("yield-wastage", "Yield and wastage", roles=OPERATIONS, params=("product_id",),
        description="Expected vs good output, damaged output, process wastage and packaging spoilage.")
def yield_wastage(db: Session, p: Params) -> Report:
    units = _units(db)
    rows = []
    for r in _runs(db, p):
        pack_damaged = sum((c.damaged_quantity for c in r.consumption if c.component_type == ItemType.PACKAGING), ZERO)
        rows.append({
            "run_no": r.run_no, "date": r.production_date, "product": db.get(Item, r.product_id).name,
            "expected": r.expected_output, "good": r.actual_good_output, "damaged": r.damaged_output,
            "yield_pct": dec.pct(r.actual_good_output / r.expected_output * 100), "yield_var": r.yield_variance_pct,
            "wastage": r.wastage_qty, "wastage_unit": units.get(r.wastage_unit_id, "") if r.wastage_unit_id else "",
            "packaging_damaged": pack_damaged, "alert": r.has_variance_alert,
        })
    return Report("yield-wastage", "Yield and wastage", [
        C("run_no", "Run"), C("date", "Date", Kind.DATE), C("product", "Product"),
        C("expected", "Expected", Kind.QTY, True), C("good", "Good", Kind.QTY, True),
        C("damaged", "Damaged output", Kind.QTY, True), C("yield_pct", "Yield %", Kind.PCT),
        C("yield_var", "Yield var %", Kind.PCT), C("wastage", "Process wastage", Kind.QTY),
        C("wastage_unit", "Unit"), C("packaging_damaged", "Packaging spoiled", Kind.QTY, True),
        C("alert", "Alert", Kind.BOOL),
    ], rows, _period(p))


@report("product-costing", "Product costing and margin", roles=OPERATIONS, params=("product_id",),
        description="Cost build-up per run, cost per good unit and gross margin against selling price.")
def product_costing(db: Session, p: Params) -> Report:
    rows = []
    for r in _runs(db, p):
        c = run_costing(db, r)
        rows.append({
            "run_no": r.run_no, "date": r.production_date, "product": db.get(Item, r.product_id).name,
            "good": c.good_output, "material": c.material, "packaging": c.packaging, "labour": c.labour,
            "power_gas": c.power_gas, "total": c.total, "cost_per_unit": c.cost_per_unit,
            "selling_price": c.selling_price, "margin": c.margin_per_unit, "margin_pct": c.margin_pct,
        })
    return Report("product-costing", "Product costing and margin", [
        C("run_no", "Run"), C("date", "Date", Kind.DATE), C("product", "Product"), C("good", "Good units", Kind.QTY, True),
        C("material", "Material", Kind.MONEY, True), C("packaging", "Packaging", Kind.MONEY, True),
        C("labour", "Labour", Kind.MONEY, True), C("power_gas", "Gas & power", Kind.MONEY, True),
        C("total", "Total cost", Kind.MONEY, True), C("cost_per_unit", "Cost / unit", Kind.RATE),
        C("selling_price", "Price (ex-GST)", Kind.MONEY), C("margin", "Margin / unit", Kind.RATE),
        C("margin_pct", "Margin %", Kind.PCT),
    ], rows, _period(p), [
        "Materials at weighted-average cost; damaged pouches are charged to the run; damaged packets are never "
        "stocked; unused cartons stay in stock; labour and gas/power are charged to good output."])


# ---- receivables --------------------------------------------------------------------------
@report("collections", "Collections", roles=FINANCE, params=("customer_id",),
        description="Receipts in the period, how they were allocated, and reversals (bounced cheques).")
def collections(db: Session, p: Params) -> Report:
    """A reversal is shown as its own negative line on the reversal date, so a past month's
    figures never change and the period total is net cash collected."""
    in_period = or_(Payment.payment_date.between(p.date_from, p.date_to),
                    Payment.reversed_on.between(p.date_from, p.date_to))
    stmt = select(Payment).where(in_period)
    if p.customer_id:
        stmt = stmt.where(Payment.customer_id == p.customer_id)
    rows = []
    for pay in db.scalars(stmt.order_by(Payment.payment_date, Payment.id)):
        allocated = sum((a.amount for a in pay.allocations), ZERO)
        base = {"customer": db.get(Customer, pay.customer_id).name, "mode": pay.mode.value,
                "reference": pay.reference_no or "",
                "invoices": ", ".join(db.get(Invoice, a.invoice_id).invoice_no for a in pay.allocations)}
        if p.date_from <= pay.payment_date <= p.date_to:
            rows.append({**base, "receipt_no": pay.receipt_no, "date": pay.payment_date, "amount": pay.amount,
                         "allocated": allocated, "advance": pay.amount - allocated,
                         "note": f"Reversed on {pay.reversed_on:%d-%m-%Y}" if pay.is_reversed else ""})
        if pay.is_reversed and p.date_from <= pay.reversed_on <= p.date_to:
            rows.append({**base, "receipt_no": f"{pay.receipt_no} (reversal)", "date": pay.reversed_on,
                         "amount": -pay.amount, "allocated": -allocated, "advance": -(pay.amount - allocated),
                         "note": pay.reversal_reason or ""})
    rows.sort(key=lambda r: (r["date"], r["receipt_no"]))
    return Report("collections", "Collections", [
        C("receipt_no", "Receipt"), C("date", "Date", Kind.DATE), C("customer", "Customer"), C("mode", "Mode"),
        C("reference", "Reference"), C("amount", "Amount", Kind.MONEY, True),
        C("allocated", "Allocated", Kind.MONEY, True), C("advance", "Advance", Kind.MONEY, True),
        C("invoices", "Against invoices"), C("note", "Note"),
    ], rows, _period(p), ["Reversed receipts appear twice: the receipt, and a negative reversal line on the reversal date."])


@report("outstanding-ageing", "Customer outstanding and ageing", roles=FINANCE, params=("customer_id",),
        description="Balance due per customer as at the end of the period, with ageing buckets.")
def outstanding_ageing(db: Session, p: Params) -> Report:
    labels = bucket_labels([int(x) for x in get_setting(db, "receivable_ageing_buckets").split(",")])
    rows = []
    for r in receivables(db, p.date_to, p.customer_id):
        row = {"code": r.customer.code, "customer": r.customer.name, "invoiced": r.invoiced, "credited": r.credited,
               "received": r.received, "advance": r.unallocated, "outstanding": r.outstanding}
        row.update({f"b{i}": r.buckets[label] for i, label in enumerate(labels)})
        rows.append(row)
    return Report("outstanding-ageing", "Customer outstanding and ageing", [
        C("code", "Code"), C("customer", "Customer"), C("invoiced", "Invoiced", Kind.MONEY, True),
        C("credited", "Credited", Kind.MONEY, True), C("received", "Received", Kind.MONEY, True),
        C("advance", "Advance", Kind.MONEY, True), C("outstanding", "Outstanding", Kind.MONEY, True),
        *[C(f"b{i}", f"{label} days", Kind.MONEY, True) for i, label in enumerate(labels)],
    ], rows, {"As at": f"{p.date_to:%d-%m-%Y}"}, ["Ageing is measured in days from the invoice date."])

