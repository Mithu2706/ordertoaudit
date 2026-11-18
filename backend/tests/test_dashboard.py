"""Owner dashboard: KPIs must equal the benchmark state (no hard-coded metrics)."""
from tests import benchmark_steps as bs
from tests.conftest import auth_headers


def test_dashboard_reflects_benchmark_state(client, db):
    b = bs.through_step7(db)
    d = client.get("/api/dashboard", headers=auth_headers(b.users["owner"])).json()
    assert d["sales"]["gross_total"] == "7875.00" and d["sales"]["net_taxable"] == "7500.00"
    assert d["collections"]["month"] == "4000.00"
    assert d["receivables"]["outstanding"] == "3875.00"
    assert d["orders"] == {"pending_approval": 1, "pending_with_shortage": 1, "awaiting_invoice": 0,
                           "awaiting_dispatch": 0}
    assert [x["code"] for x in d["stock"]["low_stock"]] == ["FG-MUR200"]  # 88 <= reorder 100
    p = d["production"]
    assert (p["runs"], p["good"], p["yield_pct"], p["alerts"]) == (1, "188.0000", "94.0000", 1)
    assert (p["latest"]["cost_per_unit"], p["latest"]["margin_pct"]) == ("31.143617", "37.7128")
    assert len(d["sales_trend"]) == 30 and d["sales_trend"][-1]["taxable"] == "7500.00"
    assert d["top_customers"][0]["total"] == "7875.00"


def test_dashboard_permissions(client, db):
    b = bs.setup(db)
    for user, code in (("owner", 200), ("admin", 200), ("auditor", 200), ("salesman_a", 403), ("production", 403)):
        assert client.get("/api/dashboard", headers=auth_headers(b.users[user])).status_code == code
