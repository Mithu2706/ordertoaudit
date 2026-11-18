"""Sales orders: salesman entry, admin approval, stock validation (benchmark steps 4-6)."""
from decimal import Decimal

import pytest

from app.models.enums import RoleCode as R
from app.models.enums import SupplyType
from app.services import availability as avail
from app.services.gst import line_tax, supply_type, totals
from tests import benchmark_steps
from tests.conftest import auth_headers

D = Decimal


# ---- GST (pure) ---------------------------------------------------------------------
def test_gst_intra_state_benchmark_retailer_a():
    t = line_tax(D("150"), D("50"), D("5"), supply_type("33", "33"))
    assert (t.taxable, t.cgst, t.sgst, t.igst, t.total) == (D("7500.00"), D("187.50"), D("187.50"), D("0.00"), D("7875.00"))
    assert (t.cgst_rate, t.sgst_rate) == (D("2.5000"), D("2.5000"))


def test_gst_inter_state_benchmark_distributor_b():
    t = line_tax(D("120"), D("50"), D("5"), supply_type("33", "29"))
    assert (t.taxable, t.cgst, t.sgst, t.igst, t.total) == (D("6000.00"), D("0.00"), D("0.00"), D("300.00"), D("6300.00"))
    assert t.igst_rate == D("5.0000")


def test_gst_rounds_each_half_separately():
    # 3 x 33.33 = 99.99; 2.5 % = 2.49975 -> 2.50 per half (each rounded on its own)
    t = line_tax(D("3"), D("33.33"), D("5"), SupplyType.INTRA_STATE)
    assert (t.cgst, t.sgst, t.tax) == (D("2.50"), D("2.50"), D("5.00"))
    agg = totals([t, line_tax(D("1"), D("10"), D("5"), SupplyType.INTER_STATE)])
    assert (agg.taxable, agg.cgst, agg.igst, agg.total) == (D("109.99"), D("2.50"), D("0.50"), D("115.49"))


# ---- fixtures ----------------------------------------------------------------------------
@pytest.fixture
def b(db):
    """Benchmark state after steps 1-3: finished goods = 238 packets."""
    return benchmark_steps.through_step3(db)


def h(b, username):
    return auth_headers(b.users[username])


def place(client, b, salesman, customer, qty, submit=True):
    res = client.post("/api/sales-orders", headers=h(b, salesman), json={
        "customer_id": b.customers[customer].id, "items": [{"product_id": b.ids["FG-MUR200"], "quantity": qty}]})
    assert res.status_code == 201, res.text
    order = res.json()
    if submit:
        order = client.post(f"/api/sales-orders/{order['id']}/submit", headers=h(b, salesman)).json()
    return order


def approve(client, b, order, **body):
    return client.post(f"/api/sales-orders/{order['id']}/approve", headers=h(b, "admin"),
                       json={"version": order["version"], **body})


# ---- benchmark steps 4-6 ------------------------------------------------------------------
def test_step4_salesman_a_orders_150_for_retailer_a(client, b):
    order = place(client, b, "salesman_a", "RET-A", "150", submit=False)
    assert order["status"] == "DRAFT" and order["order_no"].startswith("SO/")
    line = order["items"][0]
    assert (line["unit_price"], line["line_amount"]) == ("50.00", "7500.00")  # price from master
    assert (order["supply_type"], order["cgst_amount"], order["sgst_amount"], order["total_amount"]) == \
           ("INTRA_STATE", "187.50", "187.50", "7875.00")
    assert order["stock_check"] is None  # salesmen do not see on-hand figures
    submitted = client.post(f"/api/sales-orders/{order['id']}/submit", headers=h(b, "salesman_a")).json()
    assert submitted["status"] == "SUBMITTED" and submitted["has_shortage"] is False


def test_step5_admin_approves_retailer_a_and_stock_is_reserved(client, b, db):
    order = place(client, b, "salesman_a", "RET-A", "150")
    queue = client.get("/api/sales-orders?status=SUBMITTED", headers=h(b, "admin")).json()
    assert [o["order_no"] for o in queue["items"]] == [order["order_no"]]
    detail = client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "admin")).json()
    check = detail["stock_check"][0]
    assert (check["on_hand"], check["available"], check["shortage"], check["can_fulfil"]) == \
           ("238.0000", "238.0000", "0.0000", True)

    res = approve(client, b, detail)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "APPROVED" and res.json()["items"][0]["quantity_approved"] == "150.0000"
    a = avail.availability(db, b.ids["FG-MUR200"])
    assert (a.on_hand, a.reserved, a.available) == (D("238"), D("150"), D("88"))  # nothing dispatched yet


def test_step6_distributor_b_120_is_short_by_32(client, b):
    a_order = place(client, b, "salesman_a", "RET-A", "150")
    approve(client, b, a_order)

    b_order = place(client, b, "salesman_b", "DIST-B", "120")
    assert b_order["has_shortage"] is True
    assert b_order["supply_type"] == "INTER_STATE" and b_order["igst_amount"] == "300.00"  # IGST if invoiced
    detail = client.get(f"/api/sales-orders/{b_order['id']}", headers=h(b, "admin")).json()
    check = detail["stock_check"][0]
    assert (check["requested"], check["available"], check["shortage"], check["can_fulfil"]) == \
           ("120.0000", "88.0000", "32.0000", False)
    queue = client.get("/api/sales-orders?status=SUBMITTED", headers=h(b, "admin")).json()["items"]
    assert queue[0]["has_shortage"] is True

    # Full approval is refused with the exact shortage; order stays pending.
    res = approve(client, b, detail)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "insufficient_stock" and err["details"]["shortage"] == "32.0000"
    assert "short by 32" in err["message"]
    assert client.get(f"/api/sales-orders/{b_order['id']}", headers=h(b, "admin")).json()["status"] == "SUBMITTED"


def test_partial_approval_needs_reason_and_is_audited(client, b, db):
    approve(client, b, place(client, b, "salesman_a", "RET-A", "150"))
    b_order = place(client, b, "salesman_b", "DIST-B", "120")
    line = {"order_item_id": b_order["items"][0]["id"], "quantity_approved": "88"}
    assert approve(client, b, b_order, lines=[line]).status_code == 422  # no reason
    res = approve(client, b, b_order, lines=[line], reason="Only 88 available; balance to follow")
    assert res.status_code == 200
    out = res.json()
    assert out["items"][0]["quantity_approved"] == "88.0000" and out["taxable_amount"] == "4400.00"
    assert avail.availability(db, b.ids["FG-MUR200"]).available == D("0")
    log = client.get(f"/api/audit-logs?entity_type=sales_order&entity_id={b_order['id']}&action=APPROVE",
                     headers=h(b, "auditor")).json()["items"][0]
    assert log["reason"].startswith("Only 88") and log["after_data"]["items"][0]["approved"] == "88.0000"


def test_admin_price_correction_and_over_approval(client, b):
    order = place(client, b, "salesman_a", "RET-A", "10")
    item = order["items"][0]["id"]
    assert approve(client, b, order, lines=[{"order_item_id": item, "quantity_approved": "11"}],
                   reason="typo").status_code == 422
    res = approve(client, b, order, lines=[{"order_item_id": item, "quantity_approved": "10", "unit_price": "48"}],
                  reason="Festival discount agreed by owner")
    assert res.json()["items"][0]["line_amount"] == "480.00"


def test_stale_version_cannot_be_approved(client, b):
    order = place(client, b, "salesman_a", "RET-A", "10")
    res = client.post(f"/api/sales-orders/{order['id']}/approve", headers=h(b, "admin"),
                      json={"version": order["version"] - 1})
    assert res.status_code == 409


def test_reject_and_cancel_rules(client, b, db):
    order = place(client, b, "salesman_a", "RET-A", "10")
    url = f"/api/sales-orders/{order['id']}"
    assert client.post(f"{url}/reject", headers=h(b, "admin"), json={"version": order["version"]}).status_code == 422
    rej = client.post(f"{url}/reject", headers=h(b, "admin"), json={"version": order["version"], "reason": "Credit hold"})
    assert rej.json()["status"] == "REJECTED" and rej.json()["rejection_reason"] == "Credit hold"
    assert approve(client, b, rej.json()).status_code == 422

    # Admin cancelling an APPROVED order releases its reservation.
    o2 = place(client, b, "salesman_a", "RET-A", "150")
    approve(client, b, o2)
    assert avail.availability(db, b.ids["FG-MUR200"]).available == D("88")
    assert client.post(f"/api/sales-orders/{o2['id']}/cancel", headers=h(b, "salesman_a"),
                       json={"reason": "customer"}).status_code == 422  # salesman can't cancel approved
    assert client.post(f"/api/sales-orders/{o2['id']}/cancel", headers=h(b, "admin"),
                       json={"reason": "Customer withdrew"}).json()["status"] == "CANCELLED"
    assert avail.availability(db, b.ids["FG-MUR200"]).available == D("238")


def test_salesman_scope_and_editing_rules(client, b):
    # Salesman A cannot order for Distributor B (assigned to salesman B).
    res = client.post("/api/sales-orders", headers=h(b, "salesman_a"), json={
        "customer_id": b.customers["DIST-B"].id, "items": [{"product_id": b.ids["FG-MUR200"], "quantity": "1"}]})
    assert res.status_code == 404
    order = place(client, b, "salesman_a", "RET-A", "5", submit=False)
    url = f"/api/sales-orders/{order['id']}"
    body = {"customer_id": b.customers["RET-A"].id, "items": [{"product_id": b.ids["FG-MUR200"], "quantity": "7"}]}
    assert client.put(url, headers=h(b, "salesman_a"), json=body).json()["items"][0]["quantity_ordered"] == "7.0000"
    assert client.get(url, headers=h(b, "salesman_b")).status_code == 404  # not B's order
    assert client.post(f"{url}/submit", headers=h(b, "salesman_b")).status_code == 404
    client.post(f"{url}/submit", headers=h(b, "salesman_a"))
    assert client.put(url, headers=h(b, "salesman_a"), json=body).status_code == 422  # submitted: locked
    mine = client.get("/api/sales-orders", headers=h(b, "salesman_b")).json()
    assert mine["total"] == 0


def test_order_validation(client, b):
    base = {"customer_id": b.customers["RET-A"].id}
    hs = h(b, "salesman_a")
    fg = b.ids["FG-MUR200"]
    assert client.post("/api/sales-orders", headers=hs, json={**base, "items": [
        {"product_id": fg, "quantity": "1.5"}]}).status_code == 422  # whole packets
    assert client.post("/api/sales-orders", headers=hs, json={**base, "items": [
        {"product_id": b.ids["RM-FLOUR"], "quantity": "1"}]}).status_code == 422  # not a product
    assert client.post("/api/sales-orders", headers=hs, json={**base, "items": [
        {"product_id": fg, "quantity": "1"}, {"product_id": fg, "quantity": "2"}]}).status_code == 422
    assert client.post("/api/sales-orders", headers=hs, json={**base, "items": [
        {"product_id": fg, "quantity": "1", "unit_price": "1"}]}).status_code == 422  # price not accepted


def test_order_permissions(client, b, as_role):
    order = place(client, b, "salesman_a", "RET-A", "5")
    body = {"customer_id": b.customers["RET-A"].id, "items": [{"product_id": b.ids["FG-MUR200"], "quantity": "1"}]}
    assert client.post("/api/sales-orders", headers=h(b, "admin"), json=body).status_code == 403
    assert client.post(f"/api/sales-orders/{order['id']}/approve", headers=h(b, "salesman_a"),
                       json={"version": order["version"]}).status_code == 403
    assert client.post(f"/api/sales-orders/{order['id']}/approve", headers=h(b, "owner"),
                       json={"version": order["version"]}).status_code == 403
    assert client.get("/api/sales-orders", headers=h(b, "auditor")).status_code == 200
    assert client.get("/api/sales-orders", headers=h(b, "production")).status_code == 403


def test_catalog_shows_unreserved_stock(client, b):
    approve(client, b, place(client, b, "salesman_a", "RET-A", "150"))
    cat = client.get("/api/catalog", headers=h(b, "salesman_b")).json()
    assert cat == [{"product_id": b.ids["FG-MUR200"], "code": "FG-MUR200", "name": "Murukku 200 g",
                    "unit_code": "PKT", "hsn_code": "21069099", "gst_rate": "5.0000",
                    "selling_price": "50.00", "available": "88.0000"}]
