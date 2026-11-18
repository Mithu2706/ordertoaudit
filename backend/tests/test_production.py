"""BOM + production engine, including the benchmark run (steps 1-3 and costing)."""
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.models import Item, StockMovement, User
from app.models.enums import MovementType
from app.models.enums import RoleCode as R
from app.schemas.purchases import PurchaseIn, PurchaseLineIn
from app.seed.benchmark import seed_benchmark
from app.seed.reference_data import seed_demo_users
from app.services import inventory as inv
from app.services import purchases
from app.services.variance import is_alert, packaging_standard, variance_pct
from tests.conftest import auth_headers
from tests.factories import days_ago

D = Decimal


# ---- pure maths --------------------------------------------------------------------
@pytest.mark.parametrize(("planned", "actual", "expected"), [
    ("10", "10.5", "5.0000"),      # benchmark oil +5 %
    ("200", "188", "-6.0000"),     # benchmark yield -6 %
    ("40", "40", "0.0000"),
    ("188", "194", "3.1915"),      # pouches incl. 6 damaged
    ("9", "9", "0.0000"),          # cartons
])
def test_variance_pct(planned, actual, expected):
    assert variance_pct(D(planned), D(actual)) == D(expected)


def test_variance_alert_is_strictly_beyond_tolerance():
    assert variance_pct(D("0"), D("5")) is None
    assert is_alert(D("3.0000"), D("3"), D("100"), D("103")) is False
    assert is_alert(D("3.0001"), D("3"), D("100"), D("103")) is True
    assert is_alert(D("-6"), D("3"), D("200"), D("188")) is True
    assert is_alert(None, D("3"), D("0"), D("1")) is True  # used something never planned


def test_packaging_standard_scales_to_good_output():
    assert packaging_standard(D("200"), D("200"), D("188"), whole_units=True) == D("188")  # pouches
    assert packaging_standard(D("10"), D("200"), D("188"), whole_units=True) == D("9")  # 9.4 -> 9 cartons
    assert packaging_standard(D("10"), D("200"), D("188"), whole_units=False) == D("9.4")


# ---- fixtures ------------------------------------------------------------------------
@pytest.fixture
def bench(db):
    """Benchmark masters + opening stock, dated 10 days ago."""
    seed_demo_users(db, password="Demo@1234")
    ids = seed_benchmark(db, opening_date=days_ago(10))
    admin = db.scalars(select(User).where(User.username == "admin")).one()
    prod = db.scalars(select(User).where(User.username == "production")).one()
    return {"ids": ids, "admin": admin, "prod": prod, "h": auth_headers(prod)}


def step1_purchase(db, bench):
    from app.models import Supplier
    sup = db.scalars(select(Supplier).where(Supplier.code == "SUP-FLOUR")).one()
    p = purchases.create_purchase(db, PurchaseIn(
        supplier_id=sup.id, supplier_invoice_no="KFM-001", supplier_invoice_date=days_ago(8), received_date=days_ago(8),
        items=[PurchaseLineIn(item_id=bench["ids"]["RM-FLOUR"], quantity=D("60"), unit_code="KG", rate=D("45"))],
    ), bench["admin"])
    purchases.post_purchase(db, p.id, bench["admin"])


BENCH_ACTUALS = {
    "actual_good_output": "188", "labour_cost": "1200", "power_gas_cost": "600",
    "consumption": [  # filled with ids in the test
        ("RM-FLOUR", "40", "KG", "0"), ("RM-OIL", "10.5", "L", "0"), ("RM-SPICE", "1.2", "KG", "0"),
        ("PM-POUCH200", "188", "PCS", "6"), ("PM-CARTON", "9", "PCS", "0"),
    ],
}


def actuals(bench, **override):
    body = {k: v for k, v in BENCH_ACTUALS.items() if k != "consumption"}
    body["consumption"] = [
        {"item_id": bench["ids"][c], "actual_quantity": q, "unit_code": u, "damaged_quantity": d}
        for c, q, u, d in override.pop("consumption", BENCH_ACTUALS["consumption"])
    ]
    body.update(override)
    return body


def new_run(client, bench, **kw):
    res = client.post("/api/production-runs", headers=bench["h"],
                      json={"product_id": bench["ids"]["FG-MUR200"], "production_date": days_ago(7).isoformat(), **kw})
    assert res.status_code == 201, res.text
    return res.json()


def bal(db, bench, code):
    return inv.current_balance(db, bench["ids"][code]).quantity


# ---- BOM ---------------------------------------------------------------------------------
def test_seeded_bom_and_versioning(client, db, bench):
    h = bench["h"]
    boms = client.get(f"/api/boms?product_id={bench['ids']['FG-MUR200']}", headers=h).json()["items"]
    assert len(boms) == 1 and boms[0]["is_active"] and boms[0]["batch_output_qty"] == "200.0000"
    assert [(i["item_code"], i["quantity"], i["unit_code"]) for i in boms[0]["items"]] == [
        ("RM-FLOUR", "40.0000", "KG"), ("RM-OIL", "10.0000", "L"), ("RM-SPICE", "1.2000", "KG"),
        ("PM-POUCH200", "200.0000", "PCS"), ("PM-CARTON", "10.0000", "PCS")]
    # New version, yield stated in cartons (10 CTN = 200 PKT); activating retires v1.
    v2 = client.post("/api/boms", headers=h, json={
        "product_id": bench["ids"]["FG-MUR200"], "batch_output_qty": "10", "output_unit_code": "CTN",
        "items": [{"item_id": bench["ids"]["RM-FLOUR"], "quantity": "39", "unit_code": "KG"}]})
    assert v2.status_code == 201 and v2.json()["version"] == 2 and v2.json()["is_active"]
    assert client.get(f"/api/boms/{boms[0]['id']}", headers=h).json()["is_active"] is False
    run = new_run(client, bench)
    assert run["bom_version"] == 2 and run["expected_output"] == "200.0000"


def test_bom_validation(client, bench):
    h, ids = bench["h"], bench["ids"]
    base = {"product_id": ids["FG-MUR200"], "batch_output_qty": "200", "output_unit_code": "PKT"}
    fg_component = client.post("/api/boms", headers=h, json={**base, "items": [
        {"item_id": ids["FG-MUR200"], "quantity": "1", "unit_code": "PKT"}]})
    assert fg_component.status_code == 422
    wrong_unit = client.post("/api/boms", headers=h, json={**base, "items": [
        {"item_id": ids["RM-FLOUR"], "quantity": "40", "unit_code": "L"}]})
    assert wrong_unit.status_code == 422
    assert client.post("/api/boms", headers=auth_headers(bench["admin"]), json={**base, "items": [
        {"item_id": ids["RM-FLOUR"], "quantity": "40", "unit_code": "KG"}]}).status_code == 201


# ---- benchmark run -------------------------------------------------------------------------
def test_benchmark_production_run(client, db, bench):
    step1_purchase(db, bench)
    assert bal(db, bench, "RM-FLOUR") == D("160")

    run = new_run(client, bench)
    assert run["status"] == "DRAFT" and run["expected_output"] == "200.0000"
    planned = {c["item_code"]: c["planned_quantity"] for c in run["consumption"]}
    assert planned == {"RM-FLOUR": "40.0000", "RM-OIL": "10.0000", "RM-SPICE": "1.2000",
                       "PM-POUCH200": "200.0000", "PM-CARTON": "10.0000"}

    res = client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"], json=actuals(bench))
    assert res.status_code == 200, res.text
    posted = client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"])
    assert posted.status_code == 200, posted.text
    r = posted.json()

    # Stock (expected benchmark results)
    assert bal(db, bench, "RM-FLOUR") == D("120")
    assert bal(db, bench, "RM-OIL") == D("19.5")
    assert bal(db, bench, "RM-SPICE") == D("3.8")
    assert bal(db, bench, "PM-POUCH200") == D("306")  # 500 - (188 good + 6 damaged)
    assert bal(db, bench, "PM-CARTON") == D("21")  # 30 - 9
    assert bal(db, bench, "FG-MUR200") == D("238")  # 50 + 188

    # Variance
    assert r["yield_variance_pct"] == "-6.0000"
    lines = {c["item_code"]: c for c in r["consumption"]}
    assert (lines["RM-OIL"]["variance_pct"], lines["RM-OIL"]["is_variance_alert"]) == ("5.0000", True)
    assert lines["RM-FLOUR"]["variance_pct"] == "0.0000" and not lines["RM-FLOUR"]["is_variance_alert"]
    assert lines["PM-POUCH200"]["planned_quantity"] == "188.0000"
    assert lines["PM-POUCH200"]["total_consumed"] == "194.0000"
    assert lines["PM-POUCH200"]["variance_pct"] == "3.1915"
    assert lines["PM-CARTON"]["planned_quantity"] == "9.0000" and lines["PM-CARTON"]["variance_pct"] == "0.0000"
    assert r["has_variance_alert"] is True

    # Costing (weighted-average flour 43.125/kg)
    assert lines["RM-FLOUR"]["total_cost"] == "1725.00"
    assert lines["RM-OIL"]["total_cost"] == "1470.00"
    assert lines["RM-SPICE"]["total_cost"] == "240.00"
    assert lines["PM-POUCH200"]["total_cost"] == "485.00"
    assert lines["PM-CARTON"]["total_cost"] == "135.00"
    assert (r["material_cost"], r["packaging_cost"], r["total_cost"]) == ("3435.00", "620.00", "5855.00")
    assert r["cost_per_good_unit"] == "31.143617"

    # Ledger: pouches as ISSUE 188 + DAMAGE 6; FG output carries the full run cost.
    mv = {(m.item_id, m.movement_type): m for m in db.scalars(
        select(StockMovement).where(StockMovement.source_document_type == "PRODUCTION_RUN"))}
    pouch = bench["ids"]["PM-POUCH200"]
    assert mv[(pouch, MovementType.PRODUCTION_ISSUE)].quantity == D("-188")
    assert mv[(pouch, MovementType.DAMAGE)].quantity == D("-6")
    out = mv[(bench["ids"]["FG-MUR200"], MovementType.PRODUCTION_OUTPUT)]
    assert (out.quantity, out.value) == (D("188"), D("5855.00"))
    fg = inv.current_balance(db, bench["ids"]["FG-MUR200"])
    assert fg.value == D("7297.50")  # 50 x 28.85 + 5,855.00
    assert fg.avg_cost == D("30.661765")


def test_failed_posting_rolls_back_everything(client, db, bench):
    run = new_run(client, bench)
    over = [("RM-FLOUR", "40", "KG", "0"), ("RM-OIL", "50", "L", "0"), ("RM-SPICE", "1.2", "KG", "0"),
            ("PM-POUCH200", "188", "PCS", "6"), ("PM-CARTON", "9", "PCS", "0")]
    client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"], json=actuals(bench, consumption=over))
    res = client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"])
    assert res.status_code == 422
    err = res.json()["error"]
    assert err["code"] == "insufficient_stock" and err["details"]["shortage"] == "20.0000"
    # Flour was issued first in the same request -> must be rolled back.
    assert bal(db, bench, "RM-FLOUR") == D("100") and bal(db, bench, "FG-MUR200") == D("50")
    assert db.scalar(select(func.count()).select_from(StockMovement)
                     .where(StockMovement.source_document_type == "PRODUCTION_RUN")) == 0
    assert client.get(f"/api/production-runs/{run['id']}", headers=bench["h"]).json()["status"] == "DRAFT"


def test_posted_run_is_immutable(client, db, bench):
    run = new_run(client, bench)
    client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"], json=actuals(bench))
    assert client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"]).status_code == 200
    assert client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"]).status_code == 409
    assert client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"],
                      json=actuals(bench)).status_code == 409
    assert client.post(f"/api/production-runs/{run['id']}/cancel", headers=bench["h"],
                       json={"reason": "late"}).status_code == 409
    assert bal(db, bench, "FG-MUR200") == D("238")


def test_actuals_validation_and_unit_conversion(client, db, bench):
    run = new_run(client, bench)
    url = f"/api/production-runs/{run['id']}/actuals"
    full = BENCH_ACTUALS["consumption"]
    assert client.put(url, headers=bench["h"], json=actuals(bench, consumption=full[:4])).status_code == 422
    raw_damage = [("RM-FLOUR", "40", "KG", "1"), *full[1:]]
    assert client.put(url, headers=bench["h"], json=actuals(bench, consumption=raw_damage)).status_code == 422
    assert client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"]).status_code == 422  # no actuals
    in_ml = [full[0], ("RM-OIL", "10500", "ML", "0"), *full[2:]]
    res = client.put(url, headers=bench["h"], json=actuals(bench, consumption=in_ml))
    assert res.status_code == 200
    oil = next(c for c in res.json()["consumption"] if c["item_code"] == "RM-OIL")
    assert oil["actual_quantity"] == "10.5000" and oil["unit_code"] == "L"


def test_damaged_finished_packets_are_never_stocked(client, db, bench):
    run = new_run(client, bench)
    client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"],
               json=actuals(bench, actual_good_output="180", damaged_output="8"))
    r = client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"]).json()
    assert bal(db, bench, "FG-MUR200") == D("230")  # 50 + 180 good only
    assert r["damaged_output"] == "8.0000" and r["yield_variance_pct"] == "-10.0000"
    assert r["cost_per_good_unit"] == str((D(r["total_cost"]) / 180).quantize(D("0.000001")))


def test_tolerance_is_configurable_and_snapshotted(client, db, bench):
    owner = auth_headers(db.scalars(select(User).where(User.username == "owner")).one())
    client.put("/api/settings/variance_tolerance_pct", headers=owner, json={"value": "6"})
    run = new_run(client, bench)
    assert run["variance_tolerance_pct"] == "6.0000"
    client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"], json=actuals(bench))
    r = client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"]).json()
    assert r["has_variance_alert"] is False  # -6 % yield is not BEYOND 6 %
    alerts = client.get("/api/production-runs?alerts_only=true", headers=bench["h"]).json()
    assert alerts["total"] == 0


def test_alert_listing_and_permissions(client, db, bench, as_role):
    run = new_run(client, bench)
    client.put(f"/api/production-runs/{run['id']}/actuals", headers=bench["h"], json=actuals(bench))
    client.post(f"/api/production-runs/{run['id']}/post", headers=bench["h"])
    alerts = client.get("/api/production-runs?alerts_only=true", headers=as_role(R.OWNER)).json()
    assert [a["run_no"] for a in alerts["items"]] == [run["run_no"]]
    assert client.get(f"/api/production-runs/{run['id']}", headers=as_role(R.AUDITOR)).status_code == 200
    body = {"product_id": bench["ids"]["FG-MUR200"]}
    assert client.post("/api/production-runs", headers=as_role(R.SALESMAN), json=body).status_code == 403
    assert client.post("/api/production-runs", headers=as_role(R.AUDITOR), json=body).status_code == 403
    assert client.get("/api/boms", headers=as_role(R.SALESMAN)).status_code == 403


def test_benchmark_seed_is_idempotent(db, bench):
    before = db.scalar(select(func.count()).select_from(StockMovement))
    ids = seed_benchmark(db, opening_date=days_ago(10))
    assert ids == bench["ids"]
    assert db.scalar(select(func.count()).select_from(StockMovement)) == before
    assert db.scalar(select(func.count()).select_from(Item)) == 6
