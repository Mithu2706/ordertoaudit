"""Purchases: GST split, posting to stock, idempotency, all-or-nothing rollback, numbering."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import StockMovement
from app.models.enums import RoleCode as R
from app.services import inventory as inv
from app.services.numbering import financial_year
from tests.conftest import auth_headers
from tests.factories import benchmark_materials, days_ago, make_supplier

D = Decimal


@pytest.fixture
def mats(db):
    return benchmark_materials(db)


@pytest.fixture
def prod(make_user):
    return auth_headers(make_user(R.PRODUCTION))


@pytest.fixture
def opened(db, mats, make_user):
    """Benchmark opening stock for flour: 100 kg @ 42."""
    inv.post_opening_stock(db, item_id=mats["flour"].id, quantity=D("100"), unit_code="KG", unit_cost=D("42"),
                           movement_date=days_ago(10), actor=make_user(R.ADMIN))
    return mats


def body(supplier, lines, bill="BILL-1", when=None):
    when = (when or days_ago(3)).isoformat()
    return {"supplier_id": supplier.id, "supplier_invoice_no": bill, "supplier_invoice_date": when,
            "received_date": when, "items": lines}


def test_benchmark_purchase_60kg_flour_at_45(client, db, opened, prod):
    sup = make_supplier(db)
    res = client.post("/api/purchases", headers=prod,
                      json=body(sup, [{"item_id": opened["flour"].id, "quantity": "60", "unit_code": "KG", "rate": "45"}]))
    assert res.status_code == 201, res.text
    p = res.json()
    assert p["status"] == "DRAFT" and p["taxable_amount"] == "2700.00" and p["total_amount"] == "2700.00"
    assert p["purchase_no"] == f"PUR/{financial_year(date.today())}/00001"
    assert inv.current_balance(db, opened["flour"].id).quantity == D("100")  # draft does not touch stock

    posted = client.post(f"/api/purchases/{p['id']}/post", headers=prod)
    assert posted.status_code == 200 and posted.json()["status"] == "POSTED"
    bal = inv.current_balance(db, opened["flour"].id)
    assert (bal.quantity, bal.value, bal.avg_cost) == (D("160"), D("6900"), D("43.125"))
    mv = db.scalars(select(StockMovement).where(StockMovement.reference_no == p["purchase_no"])).one()
    assert mv.posting_key == f"PUR:{p['id']}:LINE:{p['items'][0]['id']}"
    assert mv.source_document_type == "PURCHASE" and mv.source_document_id == p["id"]


def test_gst_split_intra_vs_inter_state(client, db, mats, prod):
    line = [{"item_id": mats["oil"].id, "quantity": "15", "unit_code": "L", "rate": "140", "gst_rate": "5"}]
    tn = client.post("/api/purchases", headers=prod, json=body(make_supplier(db, "S-TN", "33"), line)).json()
    assert (tn["taxable_amount"], tn["cgst_amount"], tn["sgst_amount"], tn["igst_amount"], tn["total_amount"]) == \
           ("2100.00", "52.50", "52.50", "0.00", "2205.00")
    ka = client.post("/api/purchases", headers=prod, json=body(make_supplier(db, "S-KA", "29"), line)).json()
    assert (ka["cgst_amount"], ka["sgst_amount"], ka["igst_amount"], ka["total_amount"]) == \
           ("0.00", "0.00", "105.00", "2205.00")


def test_input_gst_is_not_inventory_cost(client, db, mats, prod):
    p = client.post("/api/purchases", headers=prod, json=body(make_supplier(db), [
        {"item_id": mats["oil"].id, "quantity": "10", "unit_code": "L", "rate": "140", "gst_rate": "5"}])).json()
    client.post(f"/api/purchases/{p['id']}/post", headers=prod)
    bal = inv.current_balance(db, mats["oil"].id)
    assert bal.value == D("1400.00") and bal.avg_cost == D("140")


def test_purchase_in_grams_converts_to_kg(client, db, mats, prod):
    p = client.post("/api/purchases", headers=prod, json=body(make_supplier(db), [
        {"item_id": mats["spice"].id, "quantity": "5000", "unit_code": "G", "rate": "0.2"}])).json()
    assert p["items"][0]["base_quantity"] == "5.0000" and p["items"][0]["base_unit_code"] == "KG"
    assert p["taxable_amount"] == "1000.00"
    client.post(f"/api/purchases/{p['id']}/post", headers=prod)
    assert inv.current_balance(db, mats["spice"].id).avg_cost == D("200")  # ₹200/kg


def test_posting_twice_and_editing_posted_are_refused(client, db, opened, prod):
    sup = make_supplier(db)
    lines = [{"item_id": opened["flour"].id, "quantity": "60", "unit_code": "KG", "rate": "45"}]
    p = client.post("/api/purchases", headers=prod, json=body(sup, lines)).json()
    assert client.post(f"/api/purchases/{p['id']}/post", headers=prod).status_code == 200
    assert client.post(f"/api/purchases/{p['id']}/post", headers=prod).status_code == 409
    assert client.put(f"/api/purchases/{p['id']}", headers=prod, json=body(sup, lines)).status_code == 422
    assert client.post(f"/api/purchases/{p['id']}/cancel", headers=prod, json={"reason": "oops"}).status_code == 422
    assert inv.current_balance(db, opened["flour"].id).quantity == D("160")  # posted exactly once


def test_draft_edit_and_cancel(client, db, mats, prod):
    sup = make_supplier(db)
    p = client.post("/api/purchases", headers=prod, json=body(sup, [
        {"item_id": mats["oil"].id, "quantity": "1", "unit_code": "L", "rate": "140"}])).json()
    res = client.put(f"/api/purchases/{p['id']}", headers=prod, json=body(sup, [
        {"item_id": mats["oil"].id, "quantity": "2", "unit_code": "L", "rate": "140"},
        {"item_id": mats["spice"].id, "quantity": "1", "unit_code": "KG", "rate": "200"}]))
    assert res.status_code == 200 and res.json()["taxable_amount"] == "480.00" and len(res.json()["items"]) == 2
    cancelled = client.post(f"/api/purchases/{p['id']}/cancel", headers=prod, json={"reason": "Wrong supplier"})
    assert cancelled.json()["status"] == "CANCELLED"
    assert client.post(f"/api/purchases/{p['id']}/post", headers=prod).status_code == 422


def test_duplicate_supplier_bill_and_finished_good_refused(client, db, mats, prod):
    sup = make_supplier(db)
    line = [{"item_id": mats["oil"].id, "quantity": "1", "unit_code": "L", "rate": "140"}]
    assert client.post("/api/purchases", headers=prod, json=body(sup, line)).status_code == 201
    assert client.post("/api/purchases", headers=prod, json=body(sup, line)).status_code == 409
    fg = [{"item_id": mats["murukku"].id, "quantity": "1", "unit_code": "PKT", "rate": "30"}]
    assert client.post("/api/purchases", headers=prod, json=body(sup, fg, bill="B-2")).status_code == 422


def test_validation_future_date_duplicate_lines_and_bad_unit(client, db, mats, prod):
    sup = make_supplier(db)
    line = {"item_id": mats["oil"].id, "quantity": "1", "unit_code": "L", "rate": "140"}
    future = date.fromordinal(date.today().toordinal() + 1)
    assert client.post("/api/purchases", headers=prod, json=body(sup, [line], when=future)).status_code == 422
    assert client.post("/api/purchases", headers=prod, json=body(sup, [line, line])).status_code == 422
    assert client.post("/api/purchases", headers=prod,
                       json=body(sup, [{**line, "unit_code": "KG"}])).status_code == 422  # L item, KG unit


def test_posting_is_all_or_nothing(client, db, opened, prod):
    """Line 2's item is deactivated after drafting: posting fails and line 1 is NOT received."""
    sup = make_supplier(db)
    p = client.post("/api/purchases", headers=prod, json=body(sup, [
        {"item_id": opened["flour"].id, "quantity": "60", "unit_code": "KG", "rate": "45"},
        {"item_id": opened["oil"].id, "quantity": "10", "unit_code": "L", "rate": "140"}])).json()
    opened["oil"].is_active = False
    db.flush()
    res = client.post(f"/api/purchases/{p['id']}/post", headers=prod)
    assert res.status_code == 422 and "inactive" in res.json()["error"]["message"]
    assert inv.current_balance(db, opened["flour"].id).quantity == D("100")
    assert db.scalars(select(StockMovement).where(StockMovement.source_document_type == "PURCHASE")).first() is None
    assert client.get(f"/api/purchases/{p['id']}", headers=prod).json()["status"] == "DRAFT"


def test_purchase_permissions(client, db, mats, as_role):
    sup = make_supplier(db)
    payload = body(sup, [{"item_id": mats["oil"].id, "quantity": "1", "unit_code": "L", "rate": "140"}])
    assert client.post("/api/purchases", headers=as_role(R.SALESMAN), json=payload).status_code == 403
    assert client.post("/api/purchases", headers=as_role(R.AUDITOR), json=payload).status_code == 403
    assert client.get("/api/purchases", headers=as_role(R.AUDITOR)).status_code == 200


@pytest.mark.parametrize(("on", "fy"), [
    (date(2026, 4, 1), "2026-27"), (date(2027, 3, 31), "2026-27"), (date(2026, 3, 31), "2025-26"),
    (date(2099, 12, 1), "2099-00"),
])
def test_financial_year(on, fy):
    assert financial_year(on) == fy
