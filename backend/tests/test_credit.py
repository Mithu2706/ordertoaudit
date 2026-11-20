"""Credit control at order approval.

Retailer A is seeded with a Rs 25,000 limit and 30 credit days. After benchmark steps 1-3 there are
238 packets on hand; a packet is Rs 50 + 5 % GST = Rs 52.50 incl. tax.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import Customer
from app.services import credit
from tests import benchmark_steps
from tests.test_sales import approve, h, place

D = Decimal


@pytest.fixture
def b(db):
    return benchmark_steps.through_step3(db)


def set_limit(client, b, limit: str, customer: str = "RET-A"):
    res = client.patch(f"/api/customers/{b.customers[customer].id}", headers=h(b, "admin"), json={"credit_limit": limit})
    assert res.status_code == 200, res.text


def test_review_shows_credit_position_to_staff_not_salesman(client, b):
    order = place(client, b, "salesman_a", "RET-A", "150")
    review = client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "admin")).json()
    c = review["credit"]
    assert (c["limit"], c["outstanding"], c["open_orders"], c["this_order"], c["exposure"]) == (
        "25000.00", "0.00", "0.00", "7875.00", "7875.00")
    assert (c["available"], c["exceeds"], c["excess"], c["unlimited"]) == ("25000.00", False, "0.00", False)
    assert client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "salesman_a")).json()["credit"] is None
    assert client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "auditor")).json()["credit"]["limit"] == "25000.00"


def test_approval_over_the_limit_is_refused_then_allowed_with_audited_override(client, b):
    set_limit(client, b, "10000")
    first = place(client, b, "salesman_a", "RET-A", "150")  # 7,875
    assert approve(client, b, first).status_code == 200
    second = place(client, b, "salesman_a", "RET-A", "50")  # 2,625 -> exposure 10,500 > 10,000

    review = client.get(f"/api/sales-orders/{second['id']}", headers=h(b, "admin")).json()["credit"]
    assert (review["open_orders"], review["exposure"], review["exceeds"], review["excess"]) == (
        "7875.00", "10500.00", True, "500.00")

    res = approve(client, b, second)
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "credit_limit_exceeded"
    assert "over by Rs 500.00" in err["message"]
    assert err["details"]["exposure"] == "10500.00" and err["details"]["field"] == "credit_override_reason"
    assert client.get(f"/api/sales-orders/{second['id']}", headers=h(b, "admin")).json()["status"] == "SUBMITTED"

    ok = approve(client, b, second, credit_override_reason="Owner approved; cheque collected tomorrow")
    assert ok.status_code == 200 and ok.json()["status"] == "APPROVED"
    log = client.get(f"/api/audit-logs?entity_type=sales_order&entity_id={second['id']}&action=APPROVE",
                     headers=h(b, "auditor")).json()["items"][0]
    assert log["after_data"]["credit_override"]["excess"] == "500.00"
    assert "Credit override: Owner approved" in log["reason"]
    assert "over the credit limit" in log["summary"]


def test_partial_approval_that_fits_needs_no_override(client, b):
    set_limit(client, b, "10000")
    approve(client, b, place(client, b, "salesman_a", "RET-A", "150"))  # 7,875 used
    second = place(client, b, "salesman_a", "RET-A", "50")
    line = second["items"][0]["id"]
    res = approve(client, b, second, lines=[{"order_item_id": line, "quantity_approved": "40"}], reason="Credit limit")
    assert res.status_code == 200, res.text  # 40 x 52.50 = 2,100 -> exposure 9,975


def test_payments_free_up_credit(client, b):
    set_limit(client, b, "10000")
    first = place(client, b, "salesman_a", "RET-A", "150")
    approve(client, b, first)
    client.post("/api/invoices", headers=h(b, "admin"), json={"order_id": first["id"]})
    client.post("/api/payments", headers=h(b, "admin"), json={
        "customer_id": b.customers["RET-A"].id, "amount": "4000", "mode": "UPI"})
    second = place(client, b, "salesman_a", "RET-A", "50")
    c = client.get(f"/api/sales-orders/{second['id']}", headers=h(b, "admin")).json()["credit"]
    assert (c["outstanding"], c["open_orders"], c["exposure"], c["exceeds"]) == ("3875.00", "0.00", "6500.00", False)
    assert approve(client, b, second).status_code == 200


def test_zero_limit_means_no_limit(client, b):
    set_limit(client, b, "0")
    order = place(client, b, "salesman_a", "RET-A", "200")
    c = client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "admin")).json()["credit"]
    assert c["unlimited"] is True and c["available"] is None and c["exceeds"] is False
    assert approve(client, b, order).status_code == 200


def test_override_reason_is_ignored_when_not_needed_and_validated(client, b):
    order = place(client, b, "salesman_a", "RET-A", "10")
    assert approve(client, b, order, credit_override_reason="x").status_code == 422  # too short: validation
    assert approve(client, b, order).status_code == 200


def test_invoices_past_credit_days_are_reported_overdue(client, db, b):
    order = place(client, b, "salesman_a", "RET-A", "150")
    approve(client, b, order)
    client.post("/api/invoices", headers=h(b, "admin"), json={"order_id": order["id"]})
    cust = db.get(Customer, b.customers["RET-A"].id)
    now = credit.position(db, cust)
    assert (now.outstanding, now.overdue, now.oldest_overdue_days) == (D("7875.00"), D("0.00"), None)
    later = credit.position(db, cust, as_of=date.today() + timedelta(days=40))  # credit days: 30
    assert (later.overdue, later.oldest_overdue_days) == (D("7875.00"), 40)
