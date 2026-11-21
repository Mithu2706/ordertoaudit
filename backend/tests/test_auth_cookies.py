"""Browser sessions: httpOnly session cookie + double-submit CSRF token; bearer tokens still work."""
import pytest
from fastapi.testclient import TestClient

from app.models.enums import RoleCode as R
from tests.conftest import TEST_PASSWORD


@pytest.fixture
def admin_user(make_user):
    return make_user(R.ADMIN, username="cookie_admin")


def login(client: TestClient, username: str):
    res = client.post("/api/auth/login", data={"username": username, "password": TEST_PASSWORD})
    assert res.status_code == 200, res.text
    return res


def test_login_sets_an_httponly_session_cookie_and_a_readable_csrf_cookie(client, admin_user):
    res = login(client, "cookie_admin")
    headers = res.headers.get_list("set-cookie")
    session = next(h for h in headers if h.startswith("ota_session="))
    csrf = next(h for h in headers if h.startswith("ota_csrf="))
    assert "HttpOnly" in session and "SameSite=strict" in session and "Path=/api" in session
    assert "HttpOnly" not in csrf and "SameSite=strict" in csrf and "Path=/" in csrf
    assert "Secure" not in session  # plain http in tests ("auto")
    assert res.json()["access_token"]  # API clients still get a bearer token


def test_cookie_session_reads_without_csrf_but_writes_need_it(client, admin_user):
    login(client, "cookie_admin")
    assert client.get("/api/auth/me").json()["username"] == "cookie_admin"  # GET: cookie alone is enough

    body = {"code": "SUP-CK", "name": "Cookie Supplier", "state_code": "33"}
    no_csrf = client.post("/api/suppliers", json=body)
    assert no_csrf.status_code == 403 and no_csrf.json()["error"]["code"] == "csrf_failed"
    wrong = client.post("/api/suppliers", json=body, headers={"X-CSRF-Token": "forged"})
    assert wrong.status_code == 403
    ok = client.post("/api/suppliers", json=body, headers={"X-CSRF-Token": client.cookies["ota_csrf"]})
    assert ok.status_code == 201, ok.text


def test_bearer_requests_need_no_csrf(client, admin_user):
    token = login(client, "cookie_admin").json()["access_token"]
    client.cookies.clear()
    res = client.post("/api/suppliers", headers={"Authorization": f"Bearer {token}"},
                      json={"code": "SUP-BR", "name": "Bearer Supplier", "state_code": "33"})
    assert res.status_code == 201, res.text


def test_logout_clears_the_session(client, admin_user):
    login(client, "cookie_admin")
    assert client.get("/api/auth/me").status_code == 200
    res = client.post("/api/auth/logout")
    assert res.status_code == 204
    assert all("Max-Age=0" in h or "expires=" in h.lower() for h in res.headers.get_list("set-cookie"))
    assert client.get("/api/auth/me").status_code == 401


def test_secure_flag_follows_https(client, admin_user, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setenv("COOKIE_SECURE", "true")
    get_settings.cache_clear()
    try:
        session = next(h for h in login(client, "cookie_admin").headers.get_list("set-cookie")
                       if h.startswith("ota_session="))
        assert "Secure" in session
    finally:
        get_settings.cache_clear()


def test_deactivated_user_cookie_stops_working(client, make_user, admin_user):
    login(client, "cookie_admin")
    other = make_user(R.OWNER)
    from tests.conftest import auth_headers
    client.patch(f"/api/users/{admin_user.id}", headers=auth_headers(other), json={"is_active": False})
    assert client.get("/api/auth/me").status_code == 401
