"""Shared pytest fixtures: isolated temp SQLite DB per test + seeded app/client.

Every test gets a fresh database file under tmp_path, a freshly created app
(with demo traffic disabled), and seed data. Role-specific header fixtures are
provided so analytics and customer-ownership tests can each register the exact
accounts they need with zero cross-test interference.
"""

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.api.app import create_app  # noqa: E402
from backend.db import seed  # noqa: E402


@pytest.fixture()
def app(tmp_path, monkeypatch):
    db_file = tmp_path / "simswap_test.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_file.as_posix())
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("ENABLE_DEMO_TRAFFIC", "false")
    application = create_app({"TESTING": True})
    seed.seed()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


def _register(client, username, role="analyst", password="secret123",
              name=None, email=None):
    body = {"username": username, "password": password, "role": role}
    if name:
        body["name"] = name
    if email:
        body["email"] = email
    resp = client.post("/api/auth/register", json=body)
    assert resp.status_code == 201, f"{username}: {resp.status_code} {resp.get_data(as_text=True)}"
    token = resp.get_json()["token"]
    return {"Authorization": "Bearer " + token}


@pytest.fixture()
def auth_headers(client):
    """Defaults to an 'analyst' role account (system-wide analytics access)."""
    return _register(client, "testuser", role="analyst", name="Test User")


@pytest.fixture()
def customer_headers(client):
    """User A — a customer account with its own customer profile."""
    return _register(client, "cust_a", role="customer", name="User A",
                     email="usera@example.com")


@pytest.fixture()
def customer_b_headers(client):
    """User B — a *different* customer account with its own customer profile."""
    return _register(client, "cust_b", role="customer", name="User B",
                     email="userb@example.com")


@pytest.fixture()
def analyst_headers(client):
    return _register(client, "analyst_uid", role="analyst", name="Test Analyst")


@pytest.fixture()
def admin_headers(client):
    return _register(client, "admin_uid", role="admin", name="Test Admin")


def own_customer_id(client, headers):
    """Resolve the authenticated user's own customer id from /api/auth/me."""
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.status_code
    body = resp.get_json()
    customer = body.get("customer")
    assert customer, "authenticated user must have a customer profile"
    return customer["id"]
