"""Authentication: login, tokens, inactive users."""
from datetime import UTC, datetime, timedelta

import jwt
from sqlalchemy import select

from app.core.security import create_access_token, hash_password, verify_password
from app.models import AuditLog
from app.models.enums import RoleCode
from tests.conftest import TEST_PASSWORD, auth_headers


def _login(client, username, password=TEST_PASSWORD):
    return client.post("/api/auth/login", data={"username": username, "password": password})


def test_password_hash_is_salted_and_verifiable():
    h1, h2 = hash_password("secret123"), hash_password("secret123")
    assert h1 != h2 and h1.startswith("$2b$")
    assert verify_password("secret123", h1) and not verify_password("wrong", h1)


def test_login_success_returns_token_and_role(client, make_user, db):
    user = make_user(RoleCode.ADMIN, username="priya")
    res = _login(client, "priya")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["token_type"] == "bearer"
    assert body["user"]["role"] == "ADMIN"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
    assert me.json()["username"] == "priya"
    db.refresh(user)
    assert user.last_login_at is not None
    assert db.scalars(select(AuditLog).where(AuditLog.action == "LOGIN", AuditLog.user_id == user.id)).first()


def test_wrong_password_and_unknown_user_give_same_401(client, make_user):
    make_user(RoleCode.ADMIN, username="priya")
    bad_pw, no_user = _login(client, "priya", "nope-nope"), _login(client, "ghost")
    assert bad_pw.status_code == no_user.status_code == 401
    assert bad_pw.json()["error"]["message"] == no_user.json()["error"]["message"]


def test_inactive_user_cannot_login(client, make_user):
    make_user(RoleCode.ADMIN, username="gone", active=False)
    assert _login(client, "gone").status_code == 401


def test_token_rejected_after_user_deactivated(client, make_user, db):
    user = make_user(RoleCode.ADMIN)
    headers = auth_headers(user)
    assert client.get("/api/auth/me", headers=headers).status_code == 200
    user.is_active = False
    db.flush()
    assert client.get("/api/auth/me", headers=headers).status_code == 401


def test_missing_expired_tampered_and_alg_none_tokens_rejected(client, make_user):
    user = make_user(RoleCode.ADMIN)
    assert client.get("/api/auth/me").status_code == 401

    expired = create_access_token(user.id, "ADMIN", expires_minutes=-1)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401

    forged = jwt.encode({"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(hours=1)}, "wrong-secret",
                        algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401

    unsigned = jwt.encode({"sub": str(user.id), "exp": datetime.now(UTC) + timedelta(hours=1)}, None,
                          algorithm="none")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {unsigned}"}).status_code == 401


def test_role_comes_from_database_not_token(client, make_user):
    """A token claiming ADMIN for a salesman grants nothing: the server re-reads the role."""
    salesman = make_user(RoleCode.SALESMAN)
    lying = create_access_token(salesman.id, "ADMIN")
    res = client.post("/api/suppliers", headers={"Authorization": f"Bearer {lying}"},
                      json={"code": "S1", "name": "X", "state_code": "33"})
    assert res.status_code == 403
