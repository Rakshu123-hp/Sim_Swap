"""Shared pytest fixtures: isolated temp SQLite DB per test + seeded app/client."""

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
    db_file = tmp_path / "test_simswap.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + db_file.as_posix())
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key")
    application = create_app({"TESTING": True})
    seed.seed()
    yield application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_headers(client):
    resp = client.post("/api/auth/register",
                       json={"username": "testuser", "password": "secret123",
                             "role": "analyst"})
    assert resp.status_code == 201, resp.get_json()
    token = resp.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}