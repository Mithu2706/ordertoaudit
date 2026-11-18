"""Master data: validation, uniqueness, audit trail, settings."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.gstin import gstin_check_char, gstin_error
from app.models import AuditLog, Item, StockMovement, Unit
from app.models.enums import MovementType
from app.models.enums import RoleCode as R
from app.seed.reference_data import COMPANY


def valid_gstin(state: str, pan: str = "AABCR1234M") -> str:
    first14 = f"{state}{pan}1Z"
    return first14 + gstin_check_char(first14)


@pytest.fixture
def admin(as_role):
    return as_role(R.ADMIN)


RETAILER_A = {"code": "RET-A", "name": "Retailer A", "customer_type": "RETAILER", "state_code": "33",
              "address": "T Nagar, Chennai", "city": "Chennai", "pincode": "600017"}


# ---- GSTIN -------------------------------------------------------------------------
def test_gstin_checksum_and_state_rules():
    good = valid_gstin("33")
    assert gstin_error(good, "33") is None
    assert "state code" in gstin_error(good, "29")
    tampered = good[:-1] + ("0" if good[-1] != "0" else "1")
    assert "check digit" in gstin_error(tampered)
    assert gstin_error("33ABC", None) is not None
    assert gstin_error(COMPANY["gstin"], "33") is None  # seeded company GSTIN is valid


# ---- customers ---------------------------------------------------------------------
def test_create_customer_with_gstin_writes_audit(client, admin, db):
    res = client.post("/api/customers", headers=admin, json={**RETAILER_A, "gstin": valid_gstin("33")})
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["credit_limit"] == "0.00"  # decimals serialised as exact strings
    log = db.scalars(select(AuditLog).where(AuditLog.entity_type == "customer",
                                            AuditLog.entity_id == str(body["id"]))).one()
    assert log.action == "CREATE" and log.after_data["code"] == "RET-A"


def test_customer_gstin_must_match_state(client, admin):
    res = client.post("/api/customers", headers=admin,
                      json={**RETAILER_A, "state_code": "29", "gstin": valid_gstin("33")})
    assert res.status_code == 422
    assert res.json()["error"]["details"]["field"] == "gstin"


def test_customer_unknown_state_and_duplicate_code(client, admin):
    assert client.post("/api/customers", headers=admin, json={**RETAILER_A, "state_code": "99"}).status_code == 422
    assert client.post("/api/customers", headers=admin, json=RETAILER_A).status_code == 201
    dup = client.post("/api/customers", headers=admin, json={**RETAILER_A, "code": "ret-a"})  # codes upper-cased
    assert dup.status_code == 409


def test_customer_assignment_requires_a_salesman(client, admin, make_user):
    production = make_user(R.PRODUCTION)
    res = client.post("/api/customers", headers=admin, json={**RETAILER_A, "assigned_salesman_id": production.id})
    assert res.status_code == 422


def test_update_logs_only_changed_fields_and_revalidates_gstin(client, admin, db):
    cust = client.post("/api/customers", headers=admin, json={**RETAILER_A, "gstin": valid_gstin("33")}).json()
    res = client.patch(f"/api/customers/{cust['id']}", headers=admin, json={"credit_limit": "25000", "name": "Retailer A"})
    assert res.status_code == 200 and res.json()["credit_limit"] == "25000.00"
    log = db.scalars(select(AuditLog).where(AuditLog.entity_type == "customer", AuditLog.action == "UPDATE")).one()
    assert log.before_data == {"credit_limit": "0.00"} and log.after_data == {"credit_limit": "25000.00"}
    # Moving the customer to Karnataka without fixing the TN GSTIN is refused.
    assert client.patch(f"/api/customers/{cust['id']}", headers=admin, json={"state_code": "29"}).status_code == 422


def test_explicit_null_for_required_field_is_refused(client, admin):
    cust = client.post("/api/customers", headers=admin, json=RETAILER_A).json()
    res = client.patch(f"/api/customers/{cust['id']}", headers=admin, json={"name": None})
    assert res.status_code == 422


def test_unknown_fields_and_bad_money_precision_rejected(client, admin):
    assert client.post("/api/customers", headers=admin, json={**RETAILER_A, "balance": 5}).status_code == 422
    res = client.post("/api/customers", headers=admin, json={**RETAILER_A, "credit_limit": "10.555"})
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "validation_error"


# ---- items -------------------------------------------------------------------------
PRODUCT = {"code": "FG-MUR200", "name": "Murukku 200 g", "base_unit_code": "PKT", "hsn_code": "2106",
           "gst_rate": "5", "selling_price": "50", "net_weight_g": "200"}


def test_create_product_and_salesman_can_read_price(client, admin, as_role):
    res = client.post("/api/products", headers=admin, json=PRODUCT)
    assert res.status_code == 201, res.text
    p = res.json()
    assert (p["item_type"], p["base_unit_code"], p["selling_price"]) == ("FINISHED_GOOD", "PKT", "50.00")
    listing = client.get("/api/products", headers=as_role(R.SALESMAN)).json()
    assert listing["items"][0]["selling_price"] == "50.00"


def test_product_must_use_count_unit(client, admin):
    assert client.post("/api/products", headers=admin, json={**PRODUCT, "base_unit_code": "KG"}).status_code == 422


def test_item_codes_unique_across_item_types(client, admin):
    client.post("/api/raw-materials", headers=admin, json={"code": "X-1", "name": "Flour", "base_unit_code": "KG"})
    res = client.post("/api/packaging-materials", headers=admin,
                      json={"code": "X-1", "name": "Pouch", "base_unit_code": "PCS", "packaging_kind": "POUCH"})
    assert res.status_code == 409


def test_wrong_type_lookup_is_404(client, admin):
    rm = client.post("/api/raw-materials", headers=admin,
                     json={"code": "RM-FLOUR", "name": "Flour", "base_unit_code": "KG"}).json()
    assert client.get(f"/api/products/{rm['id']}", headers=admin).status_code == 404


def test_base_unit_locked_once_stock_exists(client, admin, db, make_user):
    rm = client.post("/api/raw-materials", headers=admin,
                     json={"code": "RM-OIL", "name": "Cooking oil", "base_unit_code": "L"}).json()
    # Before any stock: changing the base unit is allowed.
    assert client.patch(f"/api/raw-materials/{rm['id']}", headers=admin, json={"base_unit_code": "ML"}).status_code == 200
    unit = db.scalars(select(Unit).where(Unit.code == "ML")).one()
    db.add(StockMovement(
        item_id=rm["id"], movement_type=MovementType.OPENING, movement_date=date(2026, 11, 1),
        quantity=Decimal("30000"), unit_id=unit.id, entered_quantity=Decimal("30000"), entered_unit_id=unit.id,
        unit_cost=Decimal("0.14"), value=Decimal("4200"), balance_after=Decimal("30000"),
        value_after=Decimal("4200"), source_document_type="OPENING", reference_no="OPEN",
        posting_key="OPEN:test:oil", created_by=make_user(R.ADMIN).id,
    ))
    db.flush()
    res = client.patch(f"/api/raw-materials/{rm['id']}", headers=admin, json={"base_unit_code": "L"})
    assert res.status_code == 422
    assert db.get(Item, rm["id"]).base_unit.code == "ML"


# ---- unit conversions -----------------------------------------------------------------
def test_unit_conversion_rules(client, admin):
    p = client.post("/api/products", headers=admin, json=PRODUCT).json()
    # Global KG->G is seeded; the same pair, or its reverse, is a conflict.
    assert client.post("/api/unit-conversions", headers=admin,
                       json={"from_unit_code": "G", "to_unit_code": "KG", "factor": "0.001"}).status_code == 409
    # Cross-dimension only for a specific item.
    assert client.post("/api/unit-conversions", headers=admin,
                       json={"from_unit_code": "PKT", "to_unit_code": "G", "factor": "200"}).status_code == 422
    # The benchmark carton: 1 CTN = 20 PKT of Murukku.
    res = client.post("/api/unit-conversions", headers=admin,
                      json={"from_unit_code": "ctn", "to_unit_code": "pkt", "factor": "20", "item_id": p["id"]})
    assert res.status_code == 201 and res.json()["factor"] == "20.000000"
    codes = {(c["from_unit_code"], c["to_unit_code"], c["item_id"])
             for c in client.get(f"/api/unit-conversions?item_id={p['id']}", headers=admin).json()}
    assert {("KG", "G", None), ("L", "ML", None), ("CTN", "PKT", p["id"])} <= codes


# ---- settings & company -----------------------------------------------------------------
def test_variance_tolerance_setting_validation(client, as_role, db):
    owner = as_role(R.OWNER)
    ok = client.put("/api/settings/variance_tolerance_pct", headers=owner, json={"value": "2.5"})
    assert ok.status_code == 200 and ok.json()["value"] == "2.5"
    assert client.put("/api/settings/variance_tolerance_pct", headers=owner, json={"value": "abc"}).status_code == 422
    assert client.put("/api/settings/variance_tolerance_pct", headers=owner, json={"value": "150"}).status_code == 422
    assert client.put("/api/settings/nope", headers=owner, json={"value": "1"}).status_code == 404
    assert db.scalars(select(AuditLog).where(AuditLog.entity_type == "app_setting")).one().after_data == {"value": "2.5"}


def test_company_profile_seeded_in_tamil_nadu(client, as_role):
    c = client.get("/api/company", headers=as_role(R.SALESMAN)).json()
    assert c["state_code"] == "33" and c["gstin"].startswith("33")
