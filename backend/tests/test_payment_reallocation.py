"""Re-allocating a receipt to different invoices of the same customer."""
import pytest

from tests import benchmark_steps
from tests.test_sales import approve, h, place


@pytest.fixture
def b(db):
    return benchmark_steps.through_step3(db)


@pytest.fixture
def two_invoices(client, b):
    """Retailer A: INV 1 = 100 packets (Rs 5,250), INV 2 = 50 packets (Rs 2,625)."""
    out = []
    for q in ("100", "50"):
        o = place(client, b, "salesman_a", "RET-A", q)
        approve(client, b, o)
        out.append(client.post("/api/invoices", headers=h(b, "admin"), json={"order_id": o["id"]}).json())
    return out


def pay(client, b, amount):
    res = client.post("/api/payments", headers=h(b, "admin"), json={
        "customer_id": b.customers["RET-A"].id, "amount": amount, "mode": "UPI", "reference_no": "UTR-7"})
    assert res.status_code == 201, res.text
    return res.json()


def realloc(client, b, p, allocations, user="admin", reason="Customer meant the later bill"):
    return client.post(f"/api/payments/{p['id']}/reallocate", headers=h(b, user),
                       json={"reason": reason, "allocations": allocations})


def bal(client, b, inv):
    return client.get(f"/api/invoices/{inv['id']}", headers=h(b, "admin")).json()["balance"]


def test_move_a_receipt_to_another_invoice(client, b, two_invoices):
    inv1, inv2 = two_invoices
    p = pay(client, b, "4000")  # FIFO: all to INV 1
    assert (bal(client, b, inv1), bal(client, b, inv2)) == ("1250.00", "2625.00")

    res = realloc(client, b, p, [{"invoice_id": inv2["id"], "amount": "2625"}])
    assert res.status_code == 200, res.text
    out = res.json()
    assert [(a["invoice_no"], a["amount"]) for a in out["allocations"]] == [(inv2["invoice_no"], "2625.00")]
    assert out["unallocated"] == "1375.00"  # the rest stays as an advance
    assert (out["receipt_no"], out["amount"]) == (p["receipt_no"], "4000.00")  # the receipt itself is unchanged
    assert (bal(client, b, inv1), bal(client, b, inv2)) == ("5250.00", "0.00")
    rec = client.get(f"/api/receivables?customer_id={b.customers['RET-A'].id}", headers=h(b, "admin")).json()[0]
    assert rec["outstanding"] == "3875.00"  # 7,875 - 4,000: moving money never changes what is owed

    log = client.get(f"/api/audit-logs?entity_type=payment&entity_id={p['id']}&action=REALLOCATE",
                     headers=h(b, "auditor")).json()["items"][0]
    assert log["before_data"]["allocations"] == [{"invoice_no": inv1["invoice_no"], "amount": "4000.00"}]
    assert log["after_data"]["advance"] == "1375.00" and log["reason"] == "Customer meant the later bill"


def test_split_across_invoices_and_back_to_all_advance(client, b, two_invoices):
    inv1, inv2 = two_invoices
    p = pay(client, b, "4000")
    split = realloc(client, b, p, [{"invoice_id": inv1["id"], "amount": "1500"},
                                   {"invoice_id": inv2["id"], "amount": "2500"}])
    assert split.status_code == 200 and split.json()["unallocated"] == "0.00"
    assert (bal(client, b, inv1), bal(client, b, inv2)) == ("3750.00", "125.00")
    empty = realloc(client, b, p, [])
    assert empty.status_code == 200 and empty.json()["unallocated"] == "4000.00"
    assert (bal(client, b, inv1), bal(client, b, inv2)) == ("5250.00", "2625.00")


def test_reallocation_rules(client, b, two_invoices):
    inv1, inv2 = two_invoices
    p = pay(client, b, "4000")
    too_much = realloc(client, b, p, [{"invoice_id": inv2["id"], "amount": "2625.01"}])
    assert too_much.status_code == 422 and "at most 2625.00" in too_much.json()["error"]["message"]
    over_receipt = realloc(client, b, p, [{"invoice_id": inv1["id"], "amount": "3000"},
                                          {"invoice_id": inv2["id"], "amount": "1001"}])
    assert over_receipt.status_code == 422
    dup = realloc(client, b, p, [{"invoice_id": inv1["id"], "amount": "1"}, {"invoice_id": inv1["id"], "amount": "1"}])
    assert dup.status_code == 422
    same = realloc(client, b, p, [{"invoice_id": inv1["id"], "amount": "4000"}])
    assert same.status_code == 422 and "unchanged" in same.json()["error"]["message"]
    assert realloc(client, b, p, [{"invoice_id": inv2["id"], "amount": "10"}], reason="x").status_code == 422

    # Another customer's invoice is refused.
    ob = place(client, b, "salesman_b", "DIST-B", "10")
    approve(client, b, ob)
    inv_b = client.post("/api/invoices", headers=h(b, "admin"), json={"order_id": ob["id"]}).json()
    assert realloc(client, b, p, [{"invoice_id": inv_b["id"], "amount": "10"}]).status_code == 422

    # A reversed receipt can't be re-allocated.
    client.post(f"/api/payments/{p['id']}/reverse", headers=h(b, "admin"), json={"reason": "Bounced"})
    assert realloc(client, b, p, [{"invoice_id": inv2["id"], "amount": "10"}]).status_code == 422
    assert bal(client, b, inv1) == "5250.00"


@pytest.mark.parametrize("user", ["owner", "auditor", "production", "salesman_a"])
def test_only_admin_can_reallocate(client, b, two_invoices, user):
    p = pay(client, b, "4000")
    assert realloc(client, b, p, [{"invoice_id": two_invoices[1]["id"], "amount": "100"}], user=user).status_code == 403


def test_moving_the_money_away_lets_an_invoice_be_cancelled(client, b, two_invoices):
    inv1, inv2 = two_invoices
    p = pay(client, b, "2000")  # all to INV 1
    url = f"/api/invoices/{inv1['id']}/credit-notes"
    body = {"reason_type": "CANCELLATION", "reason": "Billed twice by mistake", "restock": False}
    assert client.post(url, headers=h(b, "admin"), json=body).status_code == 422
    realloc(client, b, p, [{"invoice_id": inv2["id"], "amount": "2000"}])
    assert client.post(url, headers=h(b, "admin"), json=body).status_code == 201
