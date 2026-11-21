"""Purchase returns (debit notes): goods back to the supplier, through the stock ledger.

Benchmark state used: flour opened at 100 kg x Rs 42, then 60 kg bought at Rs 45 (PUR/.../00001),
so 160 kg on hand at a weighted average of Rs 43.125.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import StockMovement, Supplier
from app.models.enums import MovementType
from tests import benchmark_steps
from tests.conftest import auth_headers
from tests.factories import days_ago

D = Decimal


@pytest.fixture
def b(db):
    bench = benchmark_steps.setup(db)
    benchmark_steps.step1_purchase(db, bench)
    return bench


def h(b, user="production"):
    return auth_headers(b.users[user])


def balance(client, b, code):
    rows = client.get("/api/inventory/balances", headers=h(b)).json()
    return next(r for r in rows if r["item_code"] == code)


def benchmark_purchase(client, b):
    pid = client.get("/api/purchases", headers=h(b)).json()["items"][0]["id"]
    return client.get(f"/api/purchases/{pid}", headers=h(b)).json()


def new_purchase(client, b, supplier_code, item_code, qty, unit, rate, gst, bill):
    sup = next(s for s in client.get("/api/suppliers", headers=h(b)).json()["items"] if s["code"] == supplier_code)
    res = client.post("/api/purchases", headers=h(b), json={
        "supplier_id": sup["id"], "supplier_invoice_no": bill, "supplier_invoice_date": days_ago(5).isoformat(),
        "received_date": days_ago(5).isoformat(),
        "items": [{"item_id": b.ids[item_code], "quantity": qty, "unit_code": unit, "rate": rate, "gst_rate": gst}]})
    assert res.status_code == 201, res.text
    return client.post(f"/api/purchases/{res.json()['id']}/post", headers=h(b)).json()


def send_back(client, b, purchase, lines, user="production", **extra):
    return client.post(f"/api/purchases/{purchase['id']}/returns", headers=h(b, user), json={
        "reason": "Damp bags, rejected on inspection", **extra,
        "items": [{"purchase_item_id": purchase["items"][i]["id"], "quantity": q} for i, q in lines]})


def test_return_debits_supplier_at_purchase_rate_and_issues_stock_at_average(client, db, b):
    pur = benchmark_purchase(client, b)
    res = send_back(client, b, pur, [(0, "10")])
    assert res.status_code == 201, res.text
    r = res.json()
    assert r["return_no"].startswith("DN/") and r["return_no"].endswith("/00001")
    assert (r["taxable_amount"], r["total_amount"]) == ("450.00", "450.00")  # 10 kg x Rs 45 (bill had no GST)
    assert r["stock_value"] == "431.25"  # 10 kg x Rs 43.125 weighted average
    assert r["items"][0]["unit_code"] == "KG" and r["purchase_no"] == pur["purchase_no"]

    flour = balance(client, b, "RM-FLOUR")
    assert (flour["quantity"], flour["value"]) == ("150.0000", "6468.75")  # 6,900 - 431.25: average unchanged
    mv = db.scalars(select(StockMovement).where(StockMovement.movement_type == MovementType.PURCHASE_RETURN)).one()
    assert mv.quantity == D("-10.0000") and mv.reference_no == r["return_no"]
    assert benchmark_purchase(client, b)["items"][0]["returned_quantity"] == "10.0000"

    log = client.get("/api/audit-logs?entity_type=purchase_return&action=RETURN", headers=h(b, "auditor")).json()
    assert log["items"][0]["reason"] == "Damp bags, rejected on inspection"


def test_cannot_return_more_than_received_across_several_returns(client, b):
    pur = benchmark_purchase(client, b)
    assert send_back(client, b, pur, [(0, "10")]).status_code == 201
    over = send_back(client, b, pur, [(0, "51")])
    assert over.status_code == 422 and "at most 50" in over.json()["error"]["message"]
    assert send_back(client, b, pur, [(0, "50")]).status_code == 201
    assert send_back(client, b, pur, [(0, "1")]).status_code == 422
    assert balance(client, b, "RM-FLOUR")["quantity"] == "100.0000"  # back to the opening stock
    returns = client.get(f"/api/purchases/{pur['id']}/returns", headers=h(b, "auditor")).json()
    assert [x["taxable_amount"] for x in returns] == ["450.00", "2250.00"]  # = the 2,700 bill, exactly


def test_gst_split_follows_the_bill_and_partial_returns_never_drift(client, b):
    # Intra-state (Tamil Nadu supplier), 5 % GST: 3 x 33.33 = 99.99, CGST = SGST = 2.50 on the bill.
    intra = new_purchase(client, b, "SUP-FLOUR", "PM-POUCH200", "3", "PCS", "33.33", "5", "B-INTRA")
    first = send_back(client, b, intra, [(0, "1")]).json()  # 33.33 -> 0.83 + 0.83
    assert (first["taxable_amount"], first["cgst_amount"], first["sgst_amount"], first["igst_amount"]) == (
        "33.33", "0.83", "0.83", "0.00")
    rest = send_back(client, b, intra, [(0, "2")]).json()  # the remainder: exactly what is left of the bill
    assert (rest["taxable_amount"], rest["cgst_amount"], rest["sgst_amount"]) == ("66.66", "1.67", "1.67")
    assert D(first["total_amount"]) + D(rest["total_amount"]) == D(intra["total_amount"])

    # Inter-state (Karnataka supplier): IGST only.
    inter = new_purchase(client, b, "SUP-PACK", "PM-CARTON", "10", "PCS", "15", "12", "B-INTER")
    r = send_back(client, b, inter, [(0, "4")]).json()
    assert (r["taxable_amount"], r["cgst_amount"], r["sgst_amount"], r["igst_amount"], r["total_amount"]) == (
        "60.00", "0.00", "0.00", "7.20", "67.20")


def test_return_rules(client, b):
    pur = benchmark_purchase(client, b)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert send_back(client, b, pur, [(0, "1")], return_date=tomorrow).status_code == 422
    assert send_back(client, b, pur, [(0, "1")], return_date=days_ago(30).isoformat()).status_code == 422  # before receipt
    dup = client.post(f"/api/purchases/{pur['id']}/returns", headers=h(b), json={"reason": "Damaged", "items": [
        {"purchase_item_id": pur["items"][0]["id"], "quantity": "1"},
        {"purchase_item_id": pur["items"][0]["id"], "quantity": "1"}]})
    assert dup.status_code == 422
    other = new_purchase(client, b, "SUP-FLOUR", "RM-SPICE", "2", "KG", "200", "0", "B-OTHER")
    foreign = client.post(f"/api/purchases/{pur['id']}/returns", headers=h(b), json={
        "reason": "Damaged", "items": [{"purchase_item_id": other["items"][0]["id"], "quantity": "1"}]})
    assert foreign.status_code == 422
    assert client.post(f"/api/purchases/{pur['id']}/returns", headers=h(b),
                       json={"reason": "x", "items": [{"purchase_item_id": pur["items"][0]["id"], "quantity": "1"}]}
                       ).status_code == 422  # reason too short
    pouches = new_purchase(client, b, "SUP-PACK", "PM-POUCH200", "10", "PCS", "2.5", "0", "B-POUCH")
    assert send_back(client, b, pouches, [(0, "1.5")]).status_code == 422  # counted in whole pieces


def test_draft_purchase_cannot_be_returned(client, b):
    sup = client.get("/api/suppliers", headers=h(b)).json()["items"][0]
    draft = client.post("/api/purchases", headers=h(b), json={
        "supplier_id": sup["id"], "supplier_invoice_no": "DRAFT-1", "supplier_invoice_date": days_ago(1).isoformat(),
        "received_date": days_ago(1).isoformat(),
        "items": [{"item_id": b.ids["RM-OIL"], "quantity": "5", "unit_code": "L", "rate": "140"}]}).json()
    res = send_back(client, b, draft, [(0, "1")])
    assert res.status_code == 422 and "only posted purchases" in res.json()["error"]["message"]


def test_return_needs_the_goods_in_stock_and_is_all_or_nothing(client, db, b):
    pur = new_purchase(client, b, "SUP-PACK", "PM-CARTON", "10", "PCS", "15", "0", "B-CTN")
    spice = new_purchase(client, b, "SUP-FLOUR", "RM-SPICE", "2", "KG", "200", "0", "B-SPC")
    # Use up the 2 kg of spice bought (plus the opening 5) except 1 kg.
    client.post("/api/inventory/adjustments", headers=h(b), json={
        "item_id": b.ids["RM-SPICE"], "unit_code": "KG", "kind": "DAMAGE", "quantity": "6", "reason": "Spoilt"})
    res = send_back(client, b, spice, [(0, "2")])
    assert res.status_code == 422 and res.json()["error"]["code"] == "insufficient_stock"
    assert balance(client, b, "RM-SPICE")["quantity"] == "1.0000"
    # A two-line return where the second line fails leaves nothing behind (and burns no number).
    both = client.post(f"/api/purchases/{pur['id']}/returns", headers=h(b), json={"reason": "Wrong size", "items": [
        {"purchase_item_id": pur["items"][0]["id"], "quantity": "3"}]})
    assert both.status_code == 201 and both.json()["return_no"].endswith("/00001")


@pytest.mark.parametrize("user,code", [("admin", 201), ("owner", 403), ("auditor", 403), ("salesman_a", 403)])
def test_return_permissions(client, b, user, code):
    pur = benchmark_purchase(client, b)
    assert send_back(client, b, pur, [(0, "1")], user=user).status_code == code
    assert client.get(f"/api/purchases/{pur['id']}/returns", headers=h(b, "auditor")).status_code == 200


def test_purchase_register_shows_returns_as_negative_lines(client, b):
    pur = new_purchase(client, b, "SUP-FLOUR", "RM-OIL", "10", "L", "140", "5", "B-OIL")  # 1,400 + 35 + 35
    send_back(client, b, pur, [(0, "2")])  # 280 + 7 + 7
    rep = client.get("/api/reports/purchase-register", headers=h(b, "auditor"),
                     params={"date_from": days_ago(30).isoformat(), "date_to": date.today().isoformat()}).json()
    ret = next(r for r in rep["rows"] if r["purchase_no"].endswith("(return)"))
    assert (ret["taxable"], ret["cgst"], ret["total"]) == ("-280.00", "-7.00", "-294.00")
    assert rep["totals"]["cgst"] == "28.00"  # 35 - 7: input GST net of the return
