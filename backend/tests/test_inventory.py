"""Ledger engine: receipts, weighted average, issues, negative stock, duplicates, rollback."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.core.errors import BusinessRuleError
from app.models import StockMovement
from app.models.enums import MovementType
from app.models.enums import RoleCode as R
from app.services import inventory as inv
from tests.conftest import auth_headers
from tests.factories import benchmark_materials, days_ago

D = Decimal


@pytest.fixture
def mats(db):
    return benchmark_materials(db)


@pytest.fixture
def actor(make_user):
    return make_user(R.ADMIN)


def post(db, actor, item, mtype, qty, unit, key, when=None, **kw):
    return inv.post_movement(
        db, item_id=item.id, movement_type=mtype, quantity=D(qty), unit=unit, actor_id=actor.id,
        source_document_type="TEST", reference_no="T", posting_key=key, movement_date=when or days_ago(5), **kw,
    )


def open_flour(db, actor, flour):
    return inv.post_opening_stock(db, item_id=flour.id, quantity=D("100"), unit_code="KG", unit_cost=D("42"),
                                  movement_date=days_ago(10), actor=actor)


def test_opening_stock_sets_balance_and_value(db, mats, actor):
    m = open_flour(db, actor, mats["flour"])
    assert (m.quantity, m.balance_after, m.value_after, m.unit_cost) == (D("100"), D("100"), D("4200"), D("42"))
    bal = inv.current_balance(db, mats["flour"].id)
    assert bal.avg_cost == D("42")


def test_opening_stock_only_once_and_only_first(db, mats, actor):
    open_flour(db, actor, mats["flour"])
    with pytest.raises(BusinessRuleError, match="first movement"):
        open_flour(db, actor, mats["flour"])


def test_receipt_updates_weighted_average(db, mats, actor):
    """Benchmark: 100 kg @ 42 + 60 kg @ 45 = 160 kg worth 6,900 -> 43.125 / kg."""
    flour = mats["flour"]
    open_flour(db, actor, flour)
    m = post(db, actor, flour, MovementType.PURCHASE_RECEIPT, "60", "KG", "PUR:1", total_value=D("2700"))
    assert (m.balance_after, m.value_after, m.unit_cost) == (D("160"), D("6900"), D("45"))
    assert inv.current_balance(db, flour.id).avg_cost == D("43.125")


def test_issue_is_valued_at_weighted_average(db, mats, actor):
    flour = mats["flour"]
    open_flour(db, actor, flour)
    post(db, actor, flour, MovementType.PURCHASE_RECEIPT, "60", "KG", "PUR:1", total_value=D("2700"))
    m = post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "40", "KG", "PRD:1")
    assert m.quantity == D("-40") and m.value == D("-1725.00") and m.unit_cost == D("43.125")
    assert (m.balance_after, m.value_after) == (D("120"), D("5175.00"))


def test_issue_in_other_unit_is_converted_and_traceable(db, mats, actor):
    oil = mats["oil"]
    post(db, actor, oil, MovementType.OPENING, "30", "L", "OPEN:oil", unit_cost=D("140"))
    m = post(db, actor, oil, MovementType.PRODUCTION_ISSUE, "10500", "ML", "PRD:oil")
    assert m.quantity == D("-10.5") and m.balance_after == D("19.5")
    assert m.entered_quantity == D("10500")  # what the user typed is kept


def test_negative_stock_refused_with_shortage_and_nothing_written(db, mats, actor):
    mur = mats["murukku"]
    post(db, actor, mur, MovementType.OPENING, "88", "PKT", "OPEN:mur", unit_cost=D("31"))
    before = db.scalar(select(func.count()).select_from(StockMovement))
    with pytest.raises(inv.InsufficientStockError) as exc:
        post(db, actor, mur, MovementType.SALES_DISPATCH, "120", "PKT", "DSP:B")
    assert exc.value.details["shortage"] == "32.0000"  # benchmark Distributor B
    assert exc.value.details["available"] == "88.0000"
    assert db.scalar(select(func.count()).select_from(StockMovement)) == before
    assert inv.current_balance(db, mur.id).quantity == D("88")


def test_duplicate_posting_key_refused(db, mats, actor):
    flour = mats["flour"]
    open_flour(db, actor, flour)
    post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "1", "KG", "PRD:9:ISSUE:1")
    with pytest.raises(inv.DuplicatePostingError):
        post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "1", "KG", "PRD:9:ISSUE:1")
    assert inv.current_balance(db, flour.id).quantity == D("99")


def test_issuing_everything_clears_value_residue(db, mats, actor):
    spice = mats["spice"]
    post(db, actor, spice, MovementType.OPENING, "3", "KG", "O", total_value=D("100.00"))  # 33.333.../kg
    post(db, actor, spice, MovementType.PRODUCTION_ISSUE, "1", "KG", "I1")
    last = post(db, actor, spice, MovementType.PRODUCTION_ISSUE, "2", "KG", "I2")
    assert (last.balance_after, last.value_after) == (D("0"), D("0"))


def test_count_items_move_in_whole_units_and_cartons_convert(db, mats, actor):
    mur, pouch = mats["murukku"], mats["pouch"]
    with pytest.raises(BusinessRuleError, match="whole number"):
        post(db, actor, pouch, MovementType.OPENING, "0.5", "PCS", "O-p", unit_cost=D("2.5"))
    m = post(db, actor, mur, MovementType.OPENING, "2", "CTN", "O-m", unit_cost=D("600"))  # 2 CTN @ 600
    assert (m.quantity, m.entered_quantity, m.value) == (D("40"), D("2"), D("1200.00"))
    assert m.unit_cost == D("30")  # cost is stored per base unit (packet)


def test_backdating_before_last_movement_refused(db, mats, actor):
    flour = mats["flour"]
    open_flour(db, actor, flour)  # 10 days ago
    post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "1", "KG", "A", when=days_ago(5))
    with pytest.raises(BusinessRuleError, match="last movement is dated"):
        post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "1", "KG", "B", when=days_ago(6))


def test_inactive_item_cannot_move(db, mats, actor):
    mats["oil"].is_active = False
    db.flush()
    with pytest.raises(BusinessRuleError, match="inactive"):
        post(db, actor, mats["oil"], MovementType.OPENING, "1", "L", "X", unit_cost=D("1"))


def test_ledger_invariant_balance_equals_running_sum(db, mats, actor):
    flour = mats["flour"]
    open_flour(db, actor, flour)
    post(db, actor, flour, MovementType.PURCHASE_RECEIPT, "60", "KG", "P", total_value=D("2700"))
    post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "40", "KG", "I")
    post(db, actor, flour, MovementType.DAMAGE, "0.25", "KG", "D")
    post(db, actor, flour, MovementType.ADJUSTMENT, "0.1", "KG", "A")
    running_q, running_v = D("0"), D("0")
    for m in db.scalars(select(StockMovement).where(StockMovement.item_id == flour.id).order_by(StockMovement.id)):
        running_q += m.quantity
        running_v += m.value
        assert (m.balance_after, m.value_after) == (running_q, running_v)
    assert running_q == D("119.85")


def test_transaction_rollback_undoes_partial_postings(db, mats, actor):
    """Several postings in one unit of work: if a later one fails, the earlier ones vanish too."""
    flour, oil = mats["flour"], mats["oil"]
    open_flour(db, actor, flour)
    savepoint = db.begin_nested()
    post(db, actor, flour, MovementType.PRODUCTION_ISSUE, "40", "KG", "PRD:7:flour")
    with pytest.raises(inv.InsufficientStockError):
        post(db, actor, oil, MovementType.PRODUCTION_ISSUE, "10", "L", "PRD:7:oil")  # no oil stock
    savepoint.rollback()
    assert inv.current_balance(db, flour.id).quantity == D("100")
    assert db.scalar(select(StockMovement).where(StockMovement.posting_key == "PRD:7:flour")) is None


# ---- API -----------------------------------------------------------------------------
def test_adjustment_permissions_and_numbering(client, db, mats, make_user):
    admin, prod = make_user(R.ADMIN), make_user(R.PRODUCTION)
    open_flour(db, admin, mats["flour"])
    body = {"item_id": mats["flour"].id, "unit_code": "KG", "reason": "Physical count"}
    res = client.post("/api/inventory/adjustments", headers=auth_headers(prod),
                      json={**body, "kind": "ADJUSTMENT", "quantity": "-2"})
    assert res.status_code == 403
    res = client.post("/api/inventory/adjustments", headers=auth_headers(prod),
                      json={**body, "kind": "DAMAGE", "quantity": "1.5", "reason": "Wet bag"})
    assert res.status_code == 201, res.text
    dmg = res.json()
    assert dmg["reference_no"].startswith("ADJ/") and dmg["quantity"] == "-1.5000"
    res = client.post("/api/inventory/adjustments", headers=auth_headers(admin),
                      json={**body, "kind": "ADJUSTMENT", "quantity": "-2"})
    assert res.status_code == 201
    assert res.json()["reference_no"].endswith("00002")  # gap-free series
    assert client.post("/api/inventory/adjustments", headers=auth_headers(admin),
                       json={**body, "kind": "DAMAGE", "quantity": "-1"}).status_code == 422


def test_balances_endpoint_low_stock_and_as_of(client, db, mats, make_user):
    admin = make_user(R.ADMIN)
    open_flour(db, admin, mats["flour"])  # 10 days ago, 100 kg
    post(db, admin, mats["flour"], MovementType.PRODUCTION_ISSUE, "60", "KG", "I", when=days_ago(2))  # 40 left
    h = auth_headers(admin)
    rows = {r["item_code"]: r for r in client.get("/api/inventory/balances?item_type=RAW_MATERIAL", headers=h).json()}
    assert rows["RM-FLOUR"]["quantity"] == "40.0000" and rows["RM-FLOUR"]["low_stock"] is True  # reorder 50
    assert rows["RM-OIL"]["quantity"] == "0"
    past = {r["item_code"]: r for r in client.get(
        f"/api/inventory/balances?as_of={days_ago(5).isoformat()}", headers=h).json()}
    assert past["RM-FLOUR"]["quantity"] == "100.0000" and past["RM-FLOUR"]["avg_cost"] == "42.000000"
    low = client.get("/api/inventory/balances?low_stock_only=true", headers=h).json()
    assert [r["item_code"] for r in low] == ["RM-FLOUR"]


def test_item_ledger_opening_and_closing_for_range(client, db, mats, make_user):
    admin = make_user(R.ADMIN)
    flour = mats["flour"]
    open_flour(db, admin, flour)
    post(db, admin, flour, MovementType.PURCHASE_RECEIPT, "60", "KG", "P", when=days_ago(4), total_value=D("2700"))
    post(db, admin, flour, MovementType.PRODUCTION_ISSUE, "40", "KG", "I", when=days_ago(3))
    led = client.get(f"/api/inventory/items/{flour.id}/ledger?date_from={days_ago(4)}&date_to={days_ago(0)}",
                     headers=auth_headers(admin)).json()
    assert (led["opening_quantity"], led["total_in"], led["total_out"], led["closing_quantity"]) == \
           ("100.0000", "60.0000", "40.0000", "120.0000")
    assert [m["movement_type"] for m in led["movements"]] == ["PURCHASE_RECEIPT", "PRODUCTION_ISSUE"]
    assert led["closing_value"] == "5175.00"


def test_inventory_read_permissions(client, as_role):
    assert client.get("/api/inventory/balances", headers=as_role(R.SALESMAN)).status_code == 403
    assert client.get("/api/inventory/balances", headers=as_role(R.AUDITOR)).status_code == 200
    assert client.post("/api/inventory/opening-stock", headers=as_role(R.PRODUCTION),
                       json={"item_id": 1, "quantity": "1", "unit_code": "KG", "unit_cost": "1"}).status_code == 403


def test_future_dated_movement_rejected_by_api(client, db, mats, as_role):
    tomorrow = (days_ago(0) + timedelta(days=1)).isoformat()
    res = client.post("/api/inventory/opening-stock", headers=as_role(R.ADMIN),
                      json={"item_id": mats["flour"].id, "quantity": "1", "unit_code": "KG", "unit_cost": "1",
                            "movement_date": tomorrow})
    assert res.status_code == 422
