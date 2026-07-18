"""Owner login: signed cookie, demo-by-default (decision log #5)."""

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import settings
from app.main import app

client = TestClient(app)


@pytest.fixture()
def secret(monkeypatch):
    monkeypatch.setattr(settings, "owner_secret", "s3cret-for-tests")


def test_no_cookie_is_demo(secret):
    assert auth.resolve_user_id(None) == auth.DEMO_USER_ID


def test_forged_cookie_is_demo(secret):
    assert auth.resolve_user_id("deadbeef" * 8) == auth.DEMO_USER_ID


def test_valid_cookie_is_owner(secret):
    assert auth.resolve_user_id(auth.owner_cookie_value()) == auth.OWNER_USER_ID


def test_placeholder_secret_disables_login_entirely(monkeypatch):
    monkeypatch.setattr(settings, "owner_secret", "change-me-in-env")
    assert not auth.login_key_valid("change-me-in-env")  # even the "right" key
    assert auth.resolve_user_id(auth.owner_cookie_value()) == auth.DEMO_USER_ID


def test_login_sets_cookie_logout_clears_it(secret):
    resp = client.get("/login?key=s3cret-for-tests", follow_redirects=False)
    assert resp.status_code == 303
    cookie = resp.cookies.get(auth.COOKIE_NAME)
    assert cookie is not None
    assert auth.resolve_user_id(cookie) == auth.OWNER_USER_ID

    resp = client.get("/logout", follow_redirects=False)
    assert resp.status_code == 303
    assert f'{auth.COOKIE_NAME}=""' in resp.headers.get("set-cookie", "")


def test_wrong_key_is_403(secret):
    assert client.get("/login?key=nope", follow_redirects=False).status_code == 403
