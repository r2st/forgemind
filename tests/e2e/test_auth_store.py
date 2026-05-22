"""Tests for the persistent auth store and the api-gateway endpoints
that read/write it. Covers:

  * Login precedence: store first, env vars as fallback
  * Admin endpoints: list, upsert (create + update), delete
  * Edge cases: empty username, bad role, deleting yourself, etc.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def fresh_auth_store(monkeypatch, tmp_path):
    """Point the auth store at a brand-new temp directory and clear the
    in-process cache so each test starts from scratch."""
    cfg = tmp_path / "agent_config.json"
    monkeypatch.setenv("AGENT_CONFIG_PATH", str(cfg))
    from forgemind_common import config as _cfg
    _cfg.get_settings.cache_clear()  # type: ignore[attr-defined]
    from forgemind_common import auth_store as a
    a._invalidate_cache()
    yield a
    a._invalidate_cache()


def test_store_round_trip(fresh_auth_store):
    a = fresh_auth_store
    user = a.upsert_user("alice", "wonder", "engineer")
    assert user.username == "alice"
    assert user.role == "engineer"
    assert user.password_hash.startswith("$2")

    # authenticate
    assert a.authenticate("alice", "wonder").username == "alice"
    assert a.authenticate("alice", "wrong") is None
    assert a.authenticate("nobody", "x") is None

    # listing returns the public view (no hash)
    listing = a.list_users()
    assert listing[0]["username"] == "alice"
    assert "password_hash" not in listing[0]


def test_upsert_without_password_keeps_existing(fresh_auth_store):
    a = fresh_auth_store
    a.upsert_user("bob", "first-pw", "viewer")
    # Update role only — password stays.
    a.upsert_user("bob", None, "admin")
    assert a.authenticate("bob", "first-pw").role == "admin"


def test_upsert_new_user_without_password_blocks_login(fresh_auth_store):
    a = fresh_auth_store
    # Create with no password — store is happy but login is impossible.
    user = a.upsert_user("ghost", None, "viewer")
    fetched = a.get_user("ghost")
    assert fetched is not None
    assert fetched.username == user.username
    assert a.authenticate("ghost", "") is None
    assert a.authenticate("ghost", "anything") is None


def test_invalid_role_rejected(fresh_auth_store):
    a = fresh_auth_store
    with pytest.raises(ValueError):
        a.upsert_user("x", "p", "superuser")  # type: ignore[arg-type]


def test_empty_username_rejected(fresh_auth_store):
    a = fresh_auth_store
    with pytest.raises(ValueError):
        a.upsert_user("", "p", "viewer")


def test_delete_user(fresh_auth_store):
    a = fresh_auth_store
    a.upsert_user("temp", "p", "viewer")
    assert a.delete_user("temp") is True
    assert a.delete_user("temp") is False
    assert a.authenticate("temp", "p") is None


def test_env_lookup_match(monkeypatch, fresh_auth_store):
    a = fresh_auth_store
    monkeypatch.setenv("AUTH_ADMIN_USER", "admin")
    monkeypatch.setenv("AUTH_ADMIN_PASS", "envpass")
    assert a.env_lookup("admin", "envpass") == "admin"
    assert a.env_lookup("admin", "wrong") is None
    assert a.env_lookup("ghost", "envpass") is None


def test_env_lookup_skips_empty_envvars(monkeypatch, fresh_auth_store):
    a = fresh_auth_store
    monkeypatch.delenv("AUTH_ADMIN_USER", raising=False)
    monkeypatch.delenv("AUTH_ADMIN_PASS", raising=False)
    assert a.env_lookup("admin", "anything") is None


def test_has_store_users(fresh_auth_store):
    a = fresh_auth_store
    assert a.has_store_users() is False
    a.upsert_user("u", "p", "viewer")
    assert a.has_store_users() is True


def test_disk_persistence_survives_cache_clear(fresh_auth_store, tmp_path):
    a = fresh_auth_store
    a.upsert_user("persist", "secret", "engineer")
    a._invalidate_cache()
    # Re-load from disk
    listing = a.list_users()
    assert any(u["username"] == "persist" for u in listing)


def test_password_hash_is_bcrypt(fresh_auth_store):
    a = fresh_auth_store
    u = a.upsert_user("h", "abc", "viewer")
    # bcrypt hashes start with $2 + algo identifier + cost + salt
    assert u.password_hash.startswith("$2")
    assert len(u.password_hash) >= 50


# ----------------------------------------------------------------------
# API gateway endpoints
# ----------------------------------------------------------------------


def test_admin_list_users_endpoint(api_gateway_client, admin_token):
    """GET /api/v1/admin/auth/users should return store + env_users."""
    r = api_gateway_client.get(
        "/api/v1/admin/auth/users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert "users" in body
    assert "env_users" in body
    # The conftest sets AUTH_ADMIN_USER + AUTH_ADMIN_PASS so admin should
    # appear as an env user.
    assert any(u["username"] == "admin" for u in body["env_users"])


def test_admin_list_users_requires_admin(api_gateway_client, operator_token):
    r = api_gateway_client.get(
        "/api/v1/admin/auth/users",
        headers={"Authorization": f"Bearer {operator_token}"},
    )
    assert r.status_code == 403


def test_admin_create_user_endpoint(api_gateway_client, admin_token):
    name = f"e2e-user-{uuid.uuid4().hex[:8]}"
    r = api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "viewer", "password": "p4ssw0rd"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["username"] == name
    assert body["role"] == "viewer"

    # Login as the new user.
    login = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": name, "password": "p4ssw0rd"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["role"] == "viewer"


def test_admin_create_user_no_password_rejected(api_gateway_client, admin_token):
    name = f"e2e-nopw-{uuid.uuid4().hex[:8]}"
    r = api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "viewer"},
    )
    assert r.status_code == 400


def test_admin_create_user_bad_role_rejected(api_gateway_client, admin_token):
    r = api_gateway_client.put(
        "/api/v1/admin/auth/users/x",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "godmode", "password": "p"},
    )
    assert r.status_code == 400


def test_admin_update_user_password_only(api_gateway_client, admin_token):
    name = f"e2e-upd-{uuid.uuid4().hex[:8]}"
    api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "operator", "password": "first"},
    )
    # Update with a new password.
    r = api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "operator", "password": "second"},
    )
    assert r.status_code == 200
    # Old password fails, new one works.
    assert api_gateway_client.post(
        "/api/v1/auth/login", json={"username": name, "password": "first"}
    ).status_code == 401
    assert api_gateway_client.post(
        "/api/v1/auth/login", json={"username": name, "password": "second"}
    ).status_code == 200


def test_admin_delete_user_endpoint(api_gateway_client, admin_token):
    name = f"e2e-del-{uuid.uuid4().hex[:8]}"
    api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "viewer", "password": "p"},
    )
    r = api_gateway_client.delete(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 200
    # 404 second time.
    r = api_gateway_client.delete(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 404


def test_admin_cannot_delete_self(api_gateway_client, admin_token):
    """Deleting the currently-logged-in admin would lock you out."""
    r = api_gateway_client.delete(
        "/api/v1/admin/auth/users/admin",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert r.status_code == 400


def test_login_store_takes_precedence_over_env(api_gateway_client, admin_token, monkeypatch):
    """Once a username exists in the store, env-var creds for the same
    username are no longer honored (defense against leftover env vars)."""
    name = f"e2e-prec-{uuid.uuid4().hex[:8]}"
    # Create with one password in the store.
    api_gateway_client.put(
        f"/api/v1/admin/auth/users/{name}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"role": "viewer", "password": "store-pw"},
    )
    # Now set env vars with a different password.
    monkeypatch.setenv("AUTH_VIEWER_USER", name)
    monkeypatch.setenv("AUTH_VIEWER_PASS", "env-pw")
    # Env password must NOT work.
    bad = api_gateway_client.post(
        "/api/v1/auth/login", json={"username": name, "password": "env-pw"}
    )
    assert bad.status_code == 401
    # Store password works.
    good = api_gateway_client.post(
        "/api/v1/auth/login", json={"username": name, "password": "store-pw"}
    )
    assert good.status_code == 200


def test_login_falls_back_to_env_when_no_store_entry(api_gateway_client):
    """The conftest sets AUTH_OPERATOR_USER/AUTH_OPERATOR_PASS but does
    NOT add an operator to the store. Login should still succeed."""
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": os.environ["AUTH_OPERATOR_PASS"]},
    )
    assert r.status_code == 200
    assert r.json()["role"] == "operator"


def test_login_invalid_credentials_returns_401(api_gateway_client):
    r = api_gateway_client.post(
        "/api/v1/auth/login",
        json={"username": "totally-not-a-user", "password": "x"},
    )
    assert r.status_code == 401
