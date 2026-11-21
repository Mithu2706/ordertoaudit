"""Role-based authorization is enforced by the backend for every protected endpoint."""
import pytest

from app.models.enums import RoleCode as R

ALL = set(R)

CUSTOMER = {"code": "C-PERM", "name": "Perm Retail", "customer_type": "RETAILER", "state_code": "33",
            "address": "Chennai"}
SUPPLIER = {"code": "S-PERM", "name": "Perm Mills", "state_code": "33"}
RAW = {"code": "RM-PERM", "name": "Perm Flour", "base_unit_code": "KG"}
PACK = {"code": "PM-PERM", "name": "Perm Pouch", "base_unit_code": "PCS", "packaging_kind": "POUCH"}
PRODUCT = {"code": "FG-PERM", "name": "Perm Murukku", "base_unit_code": "PKT", "hsn_code": "2106",
           "gst_rate": "5", "selling_price": "50.00"}
USER = {"username": "perm_user", "full_name": "Perm User", "password": "Secret#123", "role": "SALESMAN"}

# (method, path, body, roles allowed). Every other role must get 403.
MATRIX = [
    ("GET", "/api/users", None, {R.ADMIN, R.OWNER}),
    ("POST", "/api/users", USER, {R.ADMIN, R.OWNER}),
    ("GET", "/api/customers", None, {R.ADMIN, R.OWNER, R.AUDITOR, R.SALESMAN}),
    ("POST", "/api/customers", CUSTOMER, {R.ADMIN}),
    ("GET", "/api/suppliers", None, {R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR}),
    ("POST", "/api/suppliers", SUPPLIER, {R.ADMIN}),
    ("GET", "/api/raw-materials", None, {R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR}),
    ("POST", "/api/raw-materials", RAW, {R.ADMIN, R.PRODUCTION}),
    ("POST", "/api/packaging-materials", PACK, {R.ADMIN, R.PRODUCTION}),
    ("GET", "/api/products", None, ALL),
    ("POST", "/api/products", PRODUCT, {R.ADMIN}),
    ("PATCH", "/api/company", {"phone": "0422-1111111"}, {R.ADMIN, R.OWNER}),
    ("GET", "/api/settings", None, {R.ADMIN, R.PRODUCTION, R.OWNER, R.AUDITOR}),
    ("PUT", "/api/settings/variance_tolerance_pct", {"value": "4"}, {R.ADMIN, R.OWNER}),
    ("GET", "/api/audit-logs", None, {R.ADMIN, R.OWNER, R.AUDITOR}),
]

CASES = [(m, p, b, role, role in allowed) for m, p, b, allowed in MATRIX for role in R]


@pytest.mark.parametrize(("method", "path", "body", "role", "allowed"), CASES,
                         ids=[f"{c[3].value}-{c[0]}-{c[1]}" for c in CASES])
def test_permission_matrix(client, as_role, method, path, body, role, allowed):
    res = client.request(method, path, json=body, headers=as_role(role))
    if allowed:
        assert res.status_code in (200, 201), res.text
    else:
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "permission_denied"


@pytest.mark.parametrize("path", ["/api/customers", "/api/products", "/api/audit-logs", "/api/units"])
def test_unauthenticated_requests_get_401(client, path):
    assert client.get(path).status_code == 401


def test_salesman_sees_only_assigned_customers(client, make_user, as_role):
    from tests.conftest import auth_headers

    admin = as_role(R.ADMIN)
    s_a, s_b = make_user(R.SALESMAN), make_user(R.SALESMAN)
    mine = client.post("/api/customers", headers=admin,
                       json={**CUSTOMER, "code": "C-MINE", "assigned_salesman_id": s_a.id}).json()
    theirs = client.post("/api/customers", headers=admin,
                         json={**CUSTOMER, "code": "C-THEIRS", "assigned_salesman_id": s_b.id}).json()

    listing = client.get("/api/customers", headers=auth_headers(s_a)).json()
    assert [c["code"] for c in listing["items"]] == ["C-MINE"]
    assert client.get(f"/api/customers/{mine['id']}", headers=auth_headers(s_a)).status_code == 200
    # Another salesman's customer is indistinguishable from a missing one.
    assert client.get(f"/api/customers/{theirs['id']}", headers=auth_headers(s_a)).status_code == 404


def test_admin_cannot_create_or_modify_owner(client, make_user, as_role):
    admin = as_role(R.ADMIN)
    res = client.post("/api/users", headers=admin, json={**USER, "username": "new_owner", "role": "OWNER"})
    assert res.status_code == 403
    owner = make_user(R.OWNER)
    assert client.patch(f"/api/users/{owner.id}", headers=admin, json={"is_active": False}).status_code == 403
    assert client.post("/api/users", headers=as_role(R.OWNER),
                       json={**USER, "username": "new_owner", "role": "OWNER"}).status_code == 201


def test_user_cannot_deactivate_self_or_change_own_role(client, make_user):
    from tests.conftest import auth_headers

    admin = make_user(R.ADMIN)
    h = auth_headers(admin)
    assert client.patch(f"/api/users/{admin.id}", headers=h, json={"is_active": False}).status_code == 422
    assert client.patch(f"/api/users/{admin.id}", headers=h, json={"role": "OWNER"}).status_code in (403, 422)


# Unit conversions need an item (packing sizes are per product), so this case creates one first.
@pytest.mark.parametrize("role", list(R), ids=[r.value for r in R])
def test_unit_conversion_permissions(client, as_role, role):
    product = client.post("/api/products", headers=as_role(R.ADMIN), json=PRODUCT).json()
    res = client.post("/api/unit-conversions", headers=as_role(role),
                      json={"from_unit_code": "CTN", "to_unit_code": "PKT", "factor": "12", "item_id": product["id"]})
    if role in {R.ADMIN, R.PRODUCTION}:
        assert res.status_code == 201, res.text
    else:
        assert res.status_code == 403 and res.json()["error"]["code"] == "permission_denied"
