"""Payment reversal: a bounced cheque re-opens the invoices it paid; the receipt stays on record."""
from datetime import date, timedelta

import pytest

from tests import benchmark_steps
from tests.test_sales import approve, h, place


@pytest.fixture
def b(db):
    return benchmark_steps.through_step3(db)


@pytest.fixture
def invoiced(client, b):
    """Retailer A: 150 packets approved and invoiced (Rs 7,875)."""
    order = place(client, b, "salesman_a", "RET-A", "150")
    approve(client, b, order)
    inv = client.post("/api/invoices", headers=h(b, "admin"), json={"order_id": order["id"]}).json()
    return inv


def pay(client, b, amount, mode="CHEQUE", ref="CHQ-000123"):
    res = client.post("/api/payments", headers=h(b, "admin"), json={
        "customer_id": b.customers["RET-A"].id, "amount": amount, "mode": mode, "reference_no": ref})
    assert res.status_code == 201, res.text
    return res.json()


def reverse(client, b, payment, user="admin", **body):
    return client.post(f"/api/payments/{payment['id']}/reverse", headers=h(b, user),
                       json={"reason": "Cheque returned: insufficient funds", **body})


def balance(client, b, inv):
    return client.get(f"/api/invoices/{inv['id']}", headers=h(b, "admin")).json()["balance"]


def outstanding(client, b):
    return client.get(f"/api/receivables?customer_id={b.customers['RET-A'].id}", headers=h(b, "admin")).json()[0]


def test_reversal_reopens_the_invoice_and_keeps_the_receipt(client, b, invoiced):
    p = pay(client, b, "4000")
    assert balance(client, b, invoiced) == "3875.00"

    res = reverse(client, b, p)
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["reversed_on"] == date.today().isoformat()
    assert out["reversal_reason"] == "Cheque returned: insufficient funds"
    assert out["receipt_no"] == p["receipt_no"] and out["amount"] == "4000.00"  # receipt kept as is
    assert out["allocations"][0]["amount"] == "4000.00"  # history kept; it just no longer counts

    assert balance(client, b, invoiced) == "7875.00"
    inv = client.get(f"/api/invoices/{invoiced['id']}", headers=h(b, "admin")).json()
    assert inv["paid_amount"] == "0.00"
    r = outstanding(client, b)
    assert (r["received"], r["outstanding"]) == ("0.00", "7875.00")

    log = client.get(f"/api/audit-logs?entity_type=payment&entity_id={p['id']}&action=REVERSE",
                     headers=h(b, "auditor")).json()["items"][0]
    assert log["reason"] == "Cheque returned: insufficient funds" and log["username"] == "admin"
    assert log["after_data"]["invoices_reopened"] == [{"invoice_id": invoiced["id"], "amount": "4000.00"}]


def test_reversal_also_removes_the_advance(client, b, invoiced):
    p = pay(client, b, "10000")  # 7,875 to the invoice + 2,125 advance
    assert p["unallocated"] == "2125.00"
    assert outstanding(client, b)["outstanding"] == "-2125.00"
    assert reverse(client, b, p).json()["unallocated"] == "0.00"
    r = outstanding(client, b)
    assert (r["unallocated_advance"], r["outstanding"]) == ("0.00", "7875.00")


def test_reversal_rules(client, b, invoiced):
    p = pay(client, b, "4000")
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    assert reverse(client, b, p, reversal_date=tomorrow).status_code == 422
    assert reverse(client, b, p, reversal_date=(date.today() - timedelta(days=1)).isoformat()).status_code == 422
    short = client.post(f"/api/payments/{p['id']}/reverse", headers=h(b, "admin"), json={"reason": "x"})
    assert short.status_code == 422
    assert client.post("/api/payments/999999/reverse", headers=h(b, "admin"), json={"reason": "Bounced"}).status_code == 404
    assert reverse(client, b, p).status_code == 200
    again = reverse(client, b, p)
    assert again.status_code == 422 and "already reversed" in again.json()["error"]["message"]
    assert balance(client, b, invoiced) == "7875.00"  # reversed once, not twice


@pytest.mark.parametrize("user", ["owner", "auditor", "production", "salesman_a"])
def test_only_admin_can_reverse(client, b, invoiced, user):
    p = pay(client, b, "4000")
    assert reverse(client, b, p, user=user).status_code == 403
    assert balance(client, b, invoiced) == "3875.00"


def test_customer_can_pay_again_after_a_bounce(client, b, invoiced):
    reverse(client, b, pay(client, b, "4000"))
    p2 = pay(client, b, "4000", mode="UPI", ref="UTR-2")
    assert p2["allocations"][0]["invoice_id"] == invoiced["id"]
    assert balance(client, b, invoiced) == "3875.00"


def test_invoice_can_be_cancelled_once_its_only_receipt_is_reversed(client, b, invoiced):
    p = pay(client, b, "4000")
    body = {"reason_type": "CANCELLATION", "reason": "Customer refused the goods", "restock": False}
    url = f"/api/invoices/{invoiced['id']}/credit-notes"
    assert client.post(url, headers=h(b, "admin"), json=body).status_code == 422  # receipt applied
    reverse(client, b, p)
    res = client.post(url, headers=h(b, "admin"), json=body)
    assert res.status_code == 201, res.text


def test_collections_report_and_dashboard_are_net_of_reversals(client, b, invoiced):
    p = pay(client, b, "4000")
    pay(client, b, "1000", mode="UPI", ref="UTR-9")
    reverse(client, b, p)
    today = date.today().isoformat()
    rep = client.get("/api/reports/collections", headers=h(b, "auditor"),
                     params={"date_from": today, "date_to": today}).json()
    rows = {r["receipt_no"]: r for r in rep["rows"]}
    assert rows[p["receipt_no"]]["amount"] == "4000.00"
    assert rows[p["receipt_no"]]["note"].startswith("Reversed on")
    reversal = rows[f"{p['receipt_no']} (reversal)"]
    assert (reversal["amount"], reversal["note"]) == ("-4000.00", "Cheque returned: insufficient funds")
    assert rep["totals"]["amount"] == "1000.00"
    assert client.get("/api/dashboard", headers=h(b, "owner")).json()["collections"]["month"] == "1000.00"


def test_reversal_raises_credit_exposure(client, b, invoiced):
    p = pay(client, b, "4000")
    order = place(client, b, "salesman_a", "RET-A", "10")
    before = client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "admin")).json()["credit"]["outstanding"]
    reverse(client, b, p)
    after = client.get(f"/api/sales-orders/{order['id']}", headers=h(b, "admin")).json()["credit"]["outstanding"]
    assert (before, after) == ("3875.00", "7875.00")
