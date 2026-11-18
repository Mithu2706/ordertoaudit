"""Production configuration: start-up safety checks and serving the built frontend."""
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, check_production_settings, get_settings
from app.main import create_app


@pytest.fixture
def settings_env(monkeypatch) -> Iterator[pytest.MonkeyPatch]:
    get_settings.cache_clear()
    yield monkeypatch
    get_settings.cache_clear()


@pytest.mark.parametrize("secret", ["", "short-secret", "change-me-to-a-long-random-string-xxxxxxxx"])
def test_production_refuses_weak_jwt_secret(secret):
    with pytest.raises(RuntimeError, match="JWT_SECRET_KEY"):
        check_production_settings(Settings(app_env="production", jwt_secret_key=secret))


def test_production_accepts_strong_secret_and_development_is_unchecked():
    check_production_settings(Settings(app_env="production", jwt_secret_key="x" * 48))
    check_production_settings(Settings(app_env="development", jwt_secret_key=""))


@pytest.fixture
def spa(tmp_path: Path, settings_env) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (tmp_path / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (tmp_path / "favicon.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path.parent / "secret.txt").write_text("nope", encoding="utf-8")
    settings_env.setenv("STATIC_DIR", str(tmp_path))
    get_settings.cache_clear()
    return TestClient(create_app())


def test_spa_routes_return_index_and_assets_are_served(spa: TestClient):
    for path in ("/", "/login", "/admin/orders/5", "/sales/new"):
        res = spa.get(path)
        assert res.status_code == 200 and "id=root" in res.text, path
        assert res.headers["cache-control"] == "no-cache"
    assert spa.get("/assets/index-abc123.js").text == "console.log(1)"
    assert spa.get("/favicon.svg").text == "<svg/>"


def test_spa_does_not_shadow_the_api(spa: TestClient):
    assert spa.get("/api/health").json() == {"status": "ok"}
    res = spa.get("/api/no-such-endpoint")
    assert res.status_code == 404 and res.json()["error"]["code"] == "not_found"
    assert spa.get("/api/dashboard").status_code == 401  # real API routes still win


def test_spa_never_serves_files_outside_the_build(spa: TestClient):
    res = spa.get("/..%2Fsecret.txt")
    assert "nope" not in res.text


def test_missing_build_fails_fast(tmp_path: Path, settings_env):
    settings_env.setenv("STATIC_DIR", str(tmp_path))
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="index.html"):
        create_app()
