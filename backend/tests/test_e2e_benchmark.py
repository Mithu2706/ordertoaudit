"""End-to-end benchmark: the whole mandatory scenario driven over HTTP, exactly as the UI does it.

Only master data is seeded directly (customers, items, BOM, opening stock, demo users).
Everything else goes through the public API: real password logins, purchase, production run,
salesman orders, admin approval, GST invoice, dispatch, payment, then reports and the
owner dashboard, checked against the benchmark's expected figures.
"""
from decimal import Decimal

from sqlalchemy.orm import Session

from app.seed.benchmark import seed_benchmark
from app.seed.reference_data import seed_demo_users
from tests.factories import days_ago

PASSWORD = "Demo@1234"
D = Decimal


def login(client, username: str) -> dict[str, str]:
    res = client.post("/api/auth/login", data={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    assert res.json()["user"]["username"] == username
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def ok(res, status: int = 200) -> dict:
    assert res.status_code == status, f"{res.request.method} {res.request.url}: {res.status_code} {res.text}"
    return res.json()


def test_full_benchmark_over_http(client, db: Session):
    seed_demo_users(db, password=PASSWORD)
    seed_benchmark(db, opening_date=days_ago(10))
    db.flush()

    admin, prod, sa, sb, owner, auditor = (login(client, u) for u in
                                           ("admin", "production", "salesman_a", "salesman_b", "owner", "auditor"))

    def balances() -> dict[str, dict]:
        return {b["item_code"]: b for b in ok(client.get("/api/inventory/balances", headers=prod))}

    ids = {code: b["item_id"] for code, b in balances().items()}
    assert balances()["RM-FLOUR"]["quantity"] == "100.0000"
    assert balances()["FG-MUR200"]["quantity"] == "50.0000"

    # ---- STEP 1: purchase 60 kg flour at Rs 45 (production supervisor records receipts) ----
    supplier = next(s for s in ok(client.get("/api/suppliers", headers=admin))["items"] if s["code"] == "SUP-FLOUR")
    purchase = ok(client.post("/api/purchases", headers=prod, json={
        "supplier_id": supplier["id"], "supplier_invoice_no": "KFM-001",
        "supplier_invoice_date": days_ago(8).isoformat(), "received_date": days_ago(8).isoformat(),
        "items": [{"item_id": ids["RM-FLOUR"], "quantity": "60", "unit_code": "KG", "rate": "45"}],
    }), 201)
    assert purchase["status"] == "DRAFT"
    assert ok(client.post(f"/api/purchases/{purchase['id']}/post", headers=prod))["status"] == "POSTED"
    assert balances()["RM-FLOUR"]["quantity"] == "160.0000"
    # posting twice must not double-count (no duplicate postings)
    assert client.post(f"/api/purchases/{purchase['id']}/post", headers=prod).status_code in (409, 422)
    assert balances()["RM-FLOUR"]["quantity"] == "160.0000"

    # ---- STEPS 2-3: production run of 1 batch (plan 200 packets) ----
    run = ok(client.post("/api/production-runs", headers=prod, json={
        "product_id": ids["FG-MUR200"], "production_date": days_ago(7).isoformat()}), 201)
    planned = {c["item_code"]: c["planned_quantity"] for c in run["consumption"]}
    assert planned["RM-FLOUR"] == "40.0000" and planned["RM-OIL"] == "10.0000"
    lines = [("RM-FLOUR", "40", "0"), ("RM-OIL", "10.5", "0"), ("RM-SPICE", "1.2", "0"),
             ("PM-POUCH200", "188", "6"), ("PM-CARTON", "9", "0")]
    ok(client.put(f"/api/production-runs/{run['id']}/actuals", headers=prod, json={
        "consumption": [{"item_id": ids[c], "actual_quantity": q, "damaged_quantity": d} for c, q, d in lines],
        "actual_good_output": "188", "labour_cost": "1200", "power_gas_cost": "600"}))
    run = ok(client.post(f"/api/production-runs/{run['id']}/post", headers=prod))
    assert run["status"] == "POSTED"
    assert client.post(f"/api/production-runs/{run['id']}/post", headers=prod).status_code in (409, 422)

    cons = {c["item_code"]: c for c in run["consumption"]}
    assert run["expected_output"] == "200.0000" and run["actual_good_output"] == "188.0000"
    assert D(run["yield_variance_pct"]) == D("-6")
    assert D(cons["RM-OIL"]["variance_pct"]) == D("5")
    assert run["has_variance_alert"] is True
    assert run["total_cost"] == "5855.00"
    assert D(run["gross_margin_pct"]) > 0

    bal = balances()
    assert bal["RM-FLOUR"]["quantity"] == "120.0000"
    assert bal["RM-OIL"]["quantity"] == "19.5000"
    assert bal["PM-POUCH200"]["quantity"] == "306.0000"
    assert bal["PM-CARTON"]["quantity"] == "21.0000"
    assert bal["FG-MUR200"]["quantity"] == "238.0000"

    # ---- STEP 4: Salesman A orders 150 packets for Retailer A (Tamil Nadu) ----
    customers = {c["code"]: c for c in ok(client.get("/api/customers", headers=sa))["items"]}
    assert set(customers) == {"RET-A"}  # a salesman sees only their own customers
    catalog = {c["code"]: c for c in ok(client.get("/api/catalog", headers=sa))}
    assert catalog["FG-MUR200"]["available"] == "238.0000"
    order_a = ok(client.post("/api/sales-orders", headers=sa, json={
        "customer_id": customers["RET-A"]["id"], "items": [{"product_id": ids["FG-MUR200"], "quantity": "150"}]}), 201)
    order_a = ok(client.post(f"/api/sales-orders/{order_a['id']}/submit", headers=sa))
    assert order_a["status"] == "SUBMITTED" and order_a["supply_type"] == "INTRA_STATE"

    # ---- STEP 5: admin verifies stock, approves, invoices (CGST+SGST) and dispatches ----
    review = ok(client.get(f"/api/sales-orders/{order_a['id']}", headers=admin))
    assert review["has_shortage"] is False and review["stock_check"][0]["available"] == "238.0000"
    order_a = ok(client.post(f"/api/sales-orders/{order_a['id']}/approve", headers=admin,
                             json={"version": review["version"]}))
    assert order_a["status"] == "APPROVED"
    # replaying the same approval (stale version) is refused
    assert client.post(f"/api/sales-orders/{order_a['id']}/approve", headers=admin,
                       json={"version": review["version"]}).status_code in (409, 422)

    invoice = ok(client.post("/api/invoices", headers=admin, json={"order_id": order_a["id"]}), 201)
    assert (invoice["taxable_amount"], invoice["cgst_amount"], invoice["sgst_amount"], invoice["igst_amount"],
            invoice["total_amount"]) == ("7500.00", "187.50", "187.50", "0.00", "7875.00")
    assert invoice["invoice_no"].startswith("INV/") and invoice["invoice_no"].endswith("/00001")
    pdf = client.get(f"/api/invoices/{invoice['id']}/pdf", headers=auditor)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")

    disp = ok(client.post("/api/dispatches", headers=admin, json={
        "order_id": order_a["id"], "vehicle_no": "TN37 AB 1234"}), 201)
    assert disp["dispatch_no"]
    assert ok(client.get(f"/api/sales-orders/{order_a['id']}", headers=admin))["status"] == "DISPATCHED"
    assert balances()["FG-MUR200"]["quantity"] == "88.0000"

    # ---- STEP 6: Salesman B orders 120 packets for Distributor B (Karnataka): short by 32 ----
    cust_b = ok(client.get("/api/customers", headers=sb))["items"][0]
    order_b = ok(client.post("/api/sales-orders", headers=sb, json={
        "customer_id": cust_b["id"], "items": [{"product_id": ids["FG-MUR200"], "quantity": "120"}]}), 201)
    order_b = ok(client.post(f"/api/sales-orders/{order_b['id']}/submit", headers=sb))
    assert order_b["supply_type"] == "INTER_STATE"
    review_b = ok(client.get(f"/api/sales-orders/{order_b['id']}", headers=admin))
    check = review_b["stock_check"][0]
    assert review_b["has_shortage"] is True
    assert (check["requested"], check["available"], check["shortage"]) == ("120.0000", "88.0000", "32.0000")
    # full approval is blocked by the backend, not just the UI
    full = client.post(f"/api/sales-orders/{order_b['id']}/approve", headers=admin, json={"version": review_b["version"]})
    assert full.status_code == 422 and "32" in full.json()["error"]["message"]
    assert ok(client.get(f"/api/sales-orders/{order_b['id']}", headers=admin))["status"] == "SUBMITTED"

    # ---- STEP 7: Retailer A pays Rs 4,000 ----
    pay = ok(client.post("/api/payments", headers=admin, json={
        "customer_id": customers["RET-A"]["id"], "amount": "4000", "mode": "UPI", "reference_no": "UTR-1"}), 201)
    assert pay["amount"] == "4000.00"
    rec = ok(client.get(f"/api/receivables?customer_id={customers['RET-A']['id']}", headers=auditor))[0]
    assert rec["outstanding"] == "3875.00"
    assert ok(client.get(f"/api/invoices/{invoice['id']}", headers=auditor))["balance"] == "3875.00"

    # ---- STEPS 8-9: reports agree with the books, for the auditor (read-only) ----
    def report(key: str) -> dict:
        return ok(client.get(f"/api/reports/{key}", headers=auditor,
                             params={"date_from": days_ago(30).isoformat(), "date_to": days_ago(0).isoformat()}))

    fg = report("finished-goods-stock")
    assert fg["rows"][0]["closing"] == "88.0000"
    gst = report("gst-summary")
    assert gst["totals"]["cgst"] == "187.50" and gst["totals"]["sgst"] == "187.50"
    ageing = report("outstanding-ageing")
    assert ageing["totals"]["outstanding"] == "3875.00"
    oil = next(r for r in report("consumption-variance")["rows"] if r["unit"] == "L")
    assert D(oil["variance_pct"]) == D("5") and oil["alert"] is True
    for key in ("sales-register", "collections", "production", "product-costing", "stock-ledger", "yield-wastage"):
        assert report(key)["row_count"] >= 1, key
    for fmt, magic in (("csv", b"\xef\xbb\xbf"), ("xlsx", b"PK"), ("pdf", b"%PDF")):
        res = client.get("/api/reports/sales-register", headers=auditor, params={"format": fmt})
        assert res.status_code == 200 and res.content.startswith(magic), fmt

    # the auditor cannot change anything
    assert client.post("/api/payments", headers=auditor, json={
        "customer_id": customers["RET-A"]["id"], "amount": "1", "mode": "CASH"}).status_code == 403

    # ---- Owner dashboard: live figures equal the benchmark ----
    dash = ok(client.get("/api/dashboard", headers=owner))
    assert dash["sales"]["net_taxable"] == "7500.00"
    assert dash["collections"]["month"] == "4000.00"
    assert dash["receivables"]["outstanding"] == "3875.00"
    assert dash["orders"]["pending_approval"] == 1 and dash["orders"]["pending_with_shortage"] == 1

    # ---- Audit trail recorded every step ----
    actions = {(a["entity_type"], a["action"]) for a in
               ok(client.get("/api/audit-logs", headers=auditor, params={"limit": 200}))["items"]}
    for expected in (("purchase", "POST"), ("production_run", "POST"), ("sales_order", "APPROVE"),
                     ("invoice", "CREATE"), ("dispatch", "DISPATCH"), ("payment", "RECEIPT")):
        assert expected in actions, expected
