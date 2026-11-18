"""GST invoices, dispatch, credit notes, payments and outstanding (benchmark steps 5-7)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import StockMovement
from app.models.enums import MovementType
from app.reports.amount_words import rupees_in_words
from app.services import availability as avail
from app.services import inventory as inv
from app.services.numbering import financial_year
from tests import benchmark_steps as bs
from tests.conftest import auth_headers
from tests.factories import days_ago

D = Decimal
FY = financial_year(date.today())


@pytest.fixture
def b(db):
    return bs.through_step3(db)  # FG = 238


@pytest.fixture
def admin(b):
    return auth_headers(b.users["admin"])


def invoice(client, admin, order_id, **kw):
    res = client.post("/api/invoices", headers=admin, json={"order_id": order_id, **kw})
    assert res.status_code == 201, res.text
    return res.json()


def dispatch(client, admin, order_id, **kw):
    return client.post("/api/dispatches", headers=admin, json={"order_id": order_id, **kw})


def fg(db, b):
    return inv.current_balance(db, b.ids["FG-MUR200"]).quantity


# ---- step 5: invoice + dispatch for Retailer A ------------------------------------------
def test_step5_retailer_a_gst_invoice(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    assert i["invoice_no"] == f"INV/{FY}/00001" and i["financial_year"] == FY
    assert (i["supply_type"], i["place_of_supply"], i["place_of_supply_state_code"]) == ("INTRA_STATE", "Tamil Nadu", "33")
    assert (i["taxable_amount"], i["cgst_amount"], i["sgst_amount"], i["igst_amount"], i["total_amount"]) == \
           ("7500.00", "187.50", "187.50", "0.00", "7875.00")
    line = i["items"][0]
    assert (line["hsn_code"], line["quantity"], line["cgst_rate"], line["sgst_rate"]) == \
           ("21069099", "150.0000", "2.5000", "2.5000")
    assert i["customer_gstin"] == b.customers["RET-A"].gstin  # snapshot
    assert i["amount_in_words"] == "Rupees Seven Thousand Eight Hundred Seventy-Five Only"
    assert i["balance"] == "7875.00" and i["status"] == "ISSUED"
    assert client.get(f"/api/sales-orders/{order.id}", headers=admin).json()["status"] == "INVOICED"
    assert client.post("/api/invoices", headers=admin, json={"order_id": order.id}).status_code == 422  # once


def test_step5_dispatch_retailer_a_leaves_88(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    assert dispatch(client, admin, order.id).status_code == 422  # must invoice first
    invoice(client, admin, order.id)
    res = dispatch(client, admin, order.id, vehicle_no="TN37 AB 1234")
    assert res.status_code == 201, res.text
    d = res.json()
    assert d["dispatch_no"] == f"DSP/{FY}/00001" and d["items"][0]["quantity"] == "150.0000"
    assert fg(db, b) == D("88")  # expected benchmark result
    assert client.get(f"/api/sales-orders/{order.id}", headers=admin).json()["status"] == "DISPATCHED"
    mv = db.scalars(select(StockMovement).where(StockMovement.movement_type == MovementType.SALES_DISPATCH)).one()
    assert mv.quantity == D("-150") and mv.value == D("-4599.26")  # 7,297.50 x 150 / 238 at weighted average
    a = avail.availability(db, b.ids["FG-MUR200"])
    assert (a.on_hand, a.reserved, a.available) == (D("88"), D("0"), D("88"))
    assert dispatch(client, admin, order.id).status_code == 422  # nothing left


def test_partial_dispatch_then_rest(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    invoice(client, admin, order.id)
    line = order.items[0].id
    assert dispatch(client, admin, order.id, items=[{"order_item_id": line, "quantity": "151"}]).status_code == 422
    assert dispatch(client, admin, order.id, items=[{"order_item_id": line, "quantity": "50"}]).status_code == 201
    assert client.get(f"/api/sales-orders/{order.id}", headers=admin).json()["status"] == "PARTIALLY_DISPATCHED"
    assert dispatch(client, admin, order.id).json()["items"][0]["quantity"] == "100.0000"
    assert fg(db, b) == D("88")


# ---- step 6: Distributor B (IGST, no invalid full dispatch) ---------------------------------
def test_step6_distributor_b_igst_and_no_full_dispatch(client, db, b, admin):
    a = bs.step4_5_order_a(db, b)
    invoice(client, admin, a.id)
    dispatch(client, admin, a.id)
    order_b = bs.place_order(db, b, "salesman_b", "DIST-B", "120")
    bs.approve(db, b, order_b, qty="88")  # only what exists; 32 short
    i = invoice(client, admin, order_b.id)
    assert (i["supply_type"], i["place_of_supply"]) == ("INTER_STATE", "Karnataka")
    assert (i["taxable_amount"], i["cgst_amount"], i["sgst_amount"], i["igst_amount"], i["total_amount"]) == \
           ("4400.00", "0.00", "0.00", "220.00", "4620.00")
    line = order_b.items[0].id
    full = dispatch(client, admin, order_b.id, items=[{"order_item_id": line, "quantity": "120"}])
    assert full.status_code == 422 and "only 88" in full.json()["error"]["message"]
    assert dispatch(client, admin, order_b.id).status_code == 201
    assert fg(db, b) == D("0")


def test_invoice_numbering_is_sequential_and_chronological(client, db, b, admin):
    o1 = bs.approve(db, b, bs.place_order(db, b, "salesman_a", "RET-A", "10"))
    o2 = bs.approve(db, b, bs.place_order(db, b, "salesman_a", "RET-A", "10"))
    o3 = bs.approve(db, b, bs.place_order(db, b, "salesman_a", "RET-A", "10"))
    assert invoice(client, admin, o1.id)["invoice_no"].endswith("/00001")
    assert invoice(client, admin, o2.id)["invoice_no"].endswith("/00002")
    # Orders were placed today, so an earlier invoice date is refused, and a failed attempt burns no number.
    res = client.post("/api/invoices", headers=admin, json={"order_id": o3.id, "invoice_date": days_ago(1).isoformat()})
    assert res.status_code == 422
    assert invoice(client, admin, o3.id)["invoice_no"].endswith("/00003")


def test_only_approved_orders_can_be_invoiced(client, db, b, admin):
    submitted = bs.place_order(db, b, "salesman_a", "RET-A", "10")
    assert client.post("/api/invoices", headers=admin, json={"order_id": submitted.id}).status_code == 422


# ---- step 7: payment and outstanding --------------------------------------------------------
def test_step7_payment_4000_leaves_3875_outstanding(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    dispatch(client, admin, order.id)
    res = client.post("/api/payments", headers=admin, json={
        "customer_id": b.customers["RET-A"].id, "amount": "4000", "mode": "UPI", "reference_no": "UTR123"})
    assert res.status_code == 201, res.text
    p = res.json()
    assert p["receipt_no"] == f"RCP/{FY}/00001" and p["unallocated"] == "0.00"
    assert p["allocations"] == [{"invoice_id": i["id"], "invoice_no": i["invoice_no"], "amount": "4000.00"}]
    assert client.get(f"/api/invoices/{i['id']}", headers=admin).json()["balance"] == "3875.00"
    rec = client.get(f"/api/receivables?customer_id={b.customers['RET-A'].id}", headers=admin).json()[0]
    assert (rec["invoiced"], rec["received"], rec["outstanding"]) == ("7875.00", "4000.00", "3875.00")
    assert rec["ageing"]["0-30"] == "3875.00" and rec["open_invoices"][0]["age_days"] == 0


def test_fifo_allocation_advance_and_over_allocation(client, db, b, admin):
    o1 = bs.approve(db, b, bs.place_order(db, b, "salesman_a", "RET-A", "10"))  # 525.00
    o2 = bs.approve(db, b, bs.place_order(db, b, "salesman_a", "RET-A", "20"))  # 1,050.00
    i1, i2 = invoice(client, admin, o1.id), invoice(client, admin, o2.id)
    cust = b.customers["RET-A"].id
    bad = client.post("/api/payments", headers=admin, json={"customer_id": cust, "amount": "100", "mode": "CASH",
                                                             "allocations": [{"invoice_id": i1["id"], "amount": "600"}]})
    assert bad.status_code == 422
    p = client.post("/api/payments", headers=admin, json={"customer_id": cust, "amount": "2000", "mode": "CASH"}).json()
    assert [(a["invoice_no"], a["amount"]) for a in p["allocations"]] == \
           [(i1["invoice_no"], "525.00"), (i2["invoice_no"], "1050.00")]
    assert p["unallocated"] == "425.00"  # advance
    rec = client.get(f"/api/receivables?customer_id={cust}", headers=admin).json()[0]
    assert (rec["invoice_outstanding"], rec["unallocated_advance"], rec["outstanding"]) == ("0.00", "425.00", "-425.00")


# ---- credit notes ----------------------------------------------------------------------------
def test_cancel_undispatched_invoice_releases_reservation(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    assert avail.availability(db, b.ids["FG-MUR200"]).available == D("88")
    res = client.post(f"/api/invoices/{i['id']}/credit-notes", headers=admin,
                      json={"reason_type": "CANCELLATION", "reason": "Wrong customer billed"})
    assert res.status_code == 201, res.text
    cn = res.json()
    assert cn["credit_note_no"] == f"CN/{FY}/00001" and cn["total_amount"] == "7875.00"
    assert (cn["cgst_amount"], cn["sgst_amount"]) == ("187.50", "187.50")
    after = client.get(f"/api/invoices/{i['id']}", headers=admin).json()
    assert (after["status"], after["balance"]) == ("CANCELLED", "0.00")
    assert client.get(f"/api/sales-orders/{order.id}", headers=admin).json()["status"] == "CANCELLED"
    assert avail.availability(db, b.ids["FG-MUR200"]).available == D("238")
    assert client.post(f"/api/invoices/{i['id']}/credit-notes", headers=admin,
                       json={"reason_type": "CANCELLATION", "reason": "again"}).status_code == 422


def test_cancel_dispatched_invoice_must_restock(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    dispatch(client, admin, order.id)
    url = f"/api/invoices/{i['id']}/credit-notes"
    assert client.post(url, headers=admin, json={"reason_type": "CANCELLATION", "reason": "Refused"}).status_code == 422
    assert client.post(url, headers=admin, json={"reason_type": "CANCELLATION", "reason": "Refused at door",
                                                 "restock": True}).status_code == 201
    assert fg(db, b) == D("238")
    ret = db.scalars(select(StockMovement).where(StockMovement.movement_type == MovementType.SALES_RETURN)).one()
    # Returned at the cost the goods left at: 150 x 30.661765 = 4,599.26 = the dispatch value.
    assert ret.quantity == D("150") and ret.value == D("4599.26")
    assert inv.current_balance(db, b.ids["FG-MUR200"]).value == D("7297.50")  # stock value fully restored


def test_partial_sales_return_and_price_adjustment(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    dispatch(client, admin, order.id)
    url, line = f"/api/invoices/{i['id']}/credit-notes", i["items"][0]["id"]
    assert client.post(url, headers=admin, json={"reason_type": "SALES_RETURN", "reason": "Too many",
                                                 "lines": [{"invoice_item_id": line, "quantity": "151"}]}).status_code == 422
    ret = client.post(url, headers=admin, json={"reason_type": "SALES_RETURN", "reason": "Crushed packets returned",
                                                "restock": True, "lines": [{"invoice_item_id": line, "quantity": "10"}]})
    assert ret.status_code == 201
    r = ret.json()
    assert (r["taxable_amount"], r["cgst_amount"], r["sgst_amount"], r["total_amount"]) == \
           ("500.00", "12.50", "12.50", "525.00")
    assert fg(db, b) == D("98")
    adj = client.post(url, headers=admin, json={"reason_type": "PRICE_ADJUSTMENT", "reason": "Rate dispute",
                                                "lines": [{"invoice_item_id": line, "taxable_amount": "100"}]}).json()
    assert adj["total_amount"] == "105.00"
    after = client.get(f"/api/invoices/{i['id']}", headers=admin).json()
    assert (after["status"], after["credited_amount"], after["balance"]) == ("PARTIALLY_CREDITED", "630.00", "7245.00")


def test_paid_invoice_cannot_be_cancelled(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    client.post("/api/payments", headers=admin, json={"customer_id": b.customers["RET-A"].id, "amount": "4000",
                                                       "mode": "UPI"})
    res = client.post(f"/api/invoices/{i['id']}/credit-notes", headers=admin,
                      json={"reason_type": "CANCELLATION", "reason": "Customer changed mind"})
    assert res.status_code == 422


# ---- PDF & words -------------------------------------------------------------------------------
def test_invoice_pdf_download(client, db, b, admin):
    order = bs.step4_5_order_a(db, b)
    i = invoice(client, admin, order.id)
    res = client.get(f"/api/invoices/{i['id']}/pdf", headers=auth_headers(b.users["auditor"]))
    assert res.status_code == 200 and res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF") and len(res.content) > 1500
    assert f'filename="INV-{FY}-00001.pdf"' in res.headers["content-disposition"]


@pytest.mark.parametrize(("amount", "words"), [
    ("7875.00", "Rupees Seven Thousand Eight Hundred Seventy-Five Only"),
    ("187.50", "Rupees One Hundred Eighty-Seven and Fifty Paise Only"),
    ("3875", "Rupees Three Thousand Eight Hundred Seventy-Five Only"),
    ("1234567.05", "Rupees Twelve Lakh Thirty-Four Thousand Five Hundred Sixty-Seven and Five Paise Only"),
    ("0", "Rupees Zero Only"),
])
def test_amount_in_words(amount, words):
    assert rupees_in_words(D(amount)) == words


def test_billing_permissions(client, db, b):
    order = bs.step4_5_order_a(db, b)
    for user in ("salesman_a", "production", "owner", "auditor"):
        h = auth_headers(b.users[user])
        assert client.post("/api/invoices", headers=h, json={"order_id": order.id}).status_code == 403
        assert client.post("/api/payments", headers=h, json={"customer_id": 1, "amount": "1",
                                                             "mode": "CASH"}).status_code == 403
    for user in ("owner", "auditor"):
        assert client.get("/api/invoices", headers=auth_headers(b.users[user])).status_code == 200
        assert client.get("/api/receivables", headers=auth_headers(b.users[user])).status_code == 200
    assert client.get("/api/invoices", headers=auth_headers(b.users["salesman_a"])).status_code == 403
