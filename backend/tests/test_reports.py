"""Benchmark step 9 + costing: every report is checked against the benchmark figures,
and every export format is checked to carry the same numbers."""
import csv
from decimal import Decimal
from io import BytesIO, StringIO

import pytest
from openpyxl import load_workbook

from tests import benchmark_steps as bs
from tests.conftest import auth_headers
from tests.factories import days_ago

D = Decimal


@pytest.fixture
def b(db):
    return bs.through_step7(db)


def run(client, b, key, user="auditor", **params):
    params.setdefault("date_from", days_ago(30).isoformat())
    res = client.get(f"/api/reports/{key}", headers=auth_headers(b.users[user]), params=params)
    assert res.status_code == 200, res.text
    return res.json()


def by(rows, key):
    return {r[key]: r for r in rows}


# ---- sales & GST ------------------------------------------------------------------------
def test_sales_register(client, b):
    rep = run(client, b, "sales-register")
    assert rep["row_count"] == 1  # Distributor B is pending, not invoiced
    r = rep["rows"][0]
    assert (r["customer"], r["supply_type"], r["taxable"], r["cgst"], r["sgst"], r["igst"], r["total"]) == \
           (b.customers["RET-A"].name, "Intra-State", "7500.00", "187.50", "187.50", "0.00", "7875.00")
    assert rep["totals"]["total"] == "7875.00"


def test_gst_summary(client, b):
    rep = run(client, b, "gst-summary")
    (r,) = rep["rows"]
    assert (r["document"], r["hsn"], r["rate"], r["taxable"], r["cgst"], r["sgst"], r["total_tax"]) == \
           ("Invoices", "21069099", "5.0000", "7500.00", "187.50", "187.50", "375.00")
    assert r["place_of_supply"] == "33 Tamil Nadu"


def test_customer_and_product_sales_and_salesman_scope(client, b):
    rows = run(client, b, "customer-sales", user="salesman_a")["rows"]
    assert [(r["code"], r["net"]) for r in rows] == [("RET-A", "7875.00")]
    assert run(client, b, "customer-sales", user="salesman_b")["rows"] == []
    (p,) = run(client, b, "product-sales")["rows"]
    assert (p["qty"], p["avg_rate"], p["taxable"]) == ("150.0000", "50.00", "7500.00")


def test_purchase_register(client, b):
    (r,) = run(client, b, "purchase-register")["rows"]
    assert (r["supplier"], r["bill_no"], r["taxable"], r["total"]) == ("Kovai Flour Mills", "KFM-001", "2700.00", "2700.00")


# ---- stock --------------------------------------------------------------------------------
def test_raw_material_stock_with_opening_balance(client, b):
    rows = by(run(client, b, "raw-material-stock", date_from=days_ago(9).isoformat())["rows"], "code")
    f = rows["RM-FLOUR"]
    assert (f["opening"], f["received"], f["issued"], f["closing"]) == ("100.0000", "60.0000", "40.0000", "120.0000")
    assert (f["avg_cost"], f["closing_value"]) == ("43.125000", "5175.00")
    assert (rows["RM-OIL"]["closing"], rows["RM-OIL"]["closing_value"]) == ("19.5000", "2730.00")
    assert rows["RM-SPICE"]["closing"] == "3.8000"


def test_packaging_and_finished_goods_stock(client, b):
    pk = by(run(client, b, "packaging-stock")["rows"], "code")
    assert (pk["PM-POUCH200"]["closing"], pk["PM-POUCH200"]["issued"]) == ("306.0000", "194.0000")
    assert pk["PM-CARTON"]["closing"] == "21.0000"
    (fg,) = run(client, b, "finished-goods-stock")["rows"]
    assert (fg["received"], fg["issued"], fg["closing"], fg["closing_value"]) == \
           ("238.0000", "150.0000", "88.0000", "2698.24")  # 7,297.50 - 4,599.26
    assert fg["low_stock"] is True  # reorder level 100


def test_stock_ledger_for_one_item(client, b):
    rep = run(client, b, "stock-ledger", item_id=b.ids["PM-POUCH200"])
    assert [(r["type"], r["in"], r["out"], r["balance"]) for r in rep["rows"]] == [
        ("OPENING", "500.0000", None, "500.0000"),
        ("PRODUCTION_ISSUE", None, "188.0000", "312.0000"),
        ("DAMAGE", None, "6.0000", "306.0000"),
    ]


# ---- production & costing -----------------------------------------------------------------
def test_production_and_variance_reports(client, b):
    (p,) = run(client, b, "production")["rows"]
    assert (p["expected"], p["good"], p["yield_var"], p["total"], p["cost_per_unit"], p["alert"]) == \
           ("200.0000", "188.0000", "-6.0000", "5855.00", "31.143617", True)
    cons = by(run(client, b, "consumption-variance")["rows"], "component")
    oil = cons["Cooking oil"]
    assert (oil["planned"], oil["consumed"], oil["variance_pct"], oil["alert"]) == ("10.0000", "10.5000", "5.0000", True)
    pouch = cons["200 g printed pouch"]
    assert (pouch["actual"], pouch["damaged"], pouch["consumed"]) == ("188.0000", "6.0000", "194.0000")
    (y,) = run(client, b, "yield-wastage")["rows"]
    assert (y["yield_pct"], y["yield_var"], y["packaging_damaged"]) == ("94.0000", "-6.0000", "6.0000")


def test_product_costing_and_gross_margin(client, b):
    (c,) = run(client, b, "product-costing")["rows"]
    assert (c["material"], c["packaging"], c["labour"], c["power_gas"], c["total"]) == \
           ("3435.00", "620.00", "1200.00", "600.00", "5855.00")
    assert (c["cost_per_unit"], c["selling_price"], c["margin"], c["margin_pct"]) == \
           ("31.143617", "50.00", "18.856383", "37.7128")


def test_run_detail_shows_gross_margin(client, b, db):
    from sqlalchemy import select

    from app.models import ProductionRun
    run_id = db.scalars(select(ProductionRun.id)).one()
    r = client.get(f"/api/production-runs/{run_id}", headers=auth_headers(b.users["owner"])).json()
    assert (r["gross_margin_per_unit"], r["gross_margin_pct"]) == ("18.856383", "37.7128")


# ---- receivables --------------------------------------------------------------------------
def test_collections_and_outstanding(client, b):
    (c,) = run(client, b, "collections")["rows"]
    assert (c["amount"], c["allocated"], c["advance"], c["mode"]) == ("4000.00", "4000.00", "0.00", "UPI")
    rep = run(client, b, "outstanding-ageing")
    (r,) = rep["rows"]  # Distributor B has no invoice yet
    assert (r["code"], r["invoiced"], r["received"], r["outstanding"], r["b0"]) == \
           ("RET-A", "7875.00", "4000.00", "3875.00", "3875.00")
    assert [c["label"] for c in rep["columns"]][-4:] == ["0-30 days", "31-60 days", "61-90 days", "90+ days"]


# ---- exports ------------------------------------------------------------------------------
def test_csv_export(client, b):
    res = client.get("/api/reports/sales-register", headers=auth_headers(b.users["auditor"]),
                     params={"date_from": days_ago(30).isoformat(), "format": "csv"})
    assert res.headers["content-type"].startswith("text/csv")
    assert 'filename="sales-register_' in res.headers["content-disposition"]
    rows = list(csv.reader(StringIO(res.content.decode("utf-8-sig"))))
    assert rows[0][:3] == ["Invoice no", "Date", "Customer"]
    assert rows[1][10] == "7875.00" and rows[-1][0] == "TOTAL" and rows[-1][10] == "7875.00"


def test_xlsx_export_has_exact_numbers(client, b):
    res = client.get("/api/reports/product-costing", headers=auth_headers(b.users["owner"]),
                     params={"date_from": days_ago(30).isoformat(), "format": "xlsx"})
    ws = load_workbook(BytesIO(res.content)).active
    assert ws["A1"].value == "Product costing and margin"
    header = [c.value for c in ws[4]]
    row = dict(zip(header, [c.value for c in ws[5]], strict=True))
    assert Decimal(str(row["Total cost"])) == D("5855.00")
    assert Decimal(str(row["Cost / unit"])) == D("31.143617")
    assert ws.cell(row=5, column=header.index("Total cost") + 1).number_format == "#,##0.00"


@pytest.mark.parametrize("key", ["sales-register", "gst-summary", "raw-material-stock", "consumption-variance",
                                 "outstanding-ageing"])
def test_pdf_export(client, b, key):
    res = client.get(f"/api/reports/{key}", headers=auth_headers(b.users["auditor"]),
                     params={"date_from": days_ago(30).isoformat(), "format": "pdf"})
    assert res.status_code == 200 and res.content.startswith(b"%PDF")


def test_empty_period_exports_cleanly(client, b):
    old = {"date_from": "2020-01-01", "date_to": "2020-01-31"}
    assert run(client, b, "sales-register", **old)["rows"] == []
    for fmt in ("csv", "xlsx", "pdf"):
        res = client.get("/api/reports/sales-register", headers=auth_headers(b.users["auditor"]),
                         params={**old, "format": fmt})
        assert res.status_code == 200


# ---- access & validation ------------------------------------------------------------------
def test_report_permissions_and_catalogue(client, b):
    h = lambda u: auth_headers(b.users[u])  # noqa: E731
    assert client.get("/api/reports/sales-register", headers=h("production")).status_code == 403
    assert client.get("/api/reports/gst-summary", headers=h("salesman_a")).status_code == 403
    assert client.get("/api/reports/production", headers=h("production")).status_code == 200
    assert {r["key"] for r in client.get("/api/reports", headers=h("salesman_a")).json()} == {"customer-sales"}
    assert len(client.get("/api/reports", headers=h("auditor")).json()) == 15
    assert client.get("/api/reports/nope", headers=h("auditor")).status_code == 404
    bad = client.get("/api/reports/sales-register", headers=h("auditor"),
                     params={"date_from": "2026-02-01", "date_to": "2026-01-01"})
    assert bad.status_code == 422
