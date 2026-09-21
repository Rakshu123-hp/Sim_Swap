"""API endpoint tests: happy paths + validation/error cases."""

from backend.db import models


# ------------------------------------------------------------------ auth

def test_register_and_login(client):
    resp = client.post("/api/auth/register",
                       json={"username": "alice", "password": "secret123"})
    assert resp.status_code == 201
    assert resp.get_json()["user"]["role"] == "analyst"

    login = client.post("/api/auth/login",
                        json={"username": "alice", "password": "secret123"})
    assert login.status_code == 200
    assert "token" in login.get_json()


def test_register_with_email_and_login_by_email(client):
    resp = client.post("/api/auth/register",
                       json={"username": "emma", "email": "Emma@Example.com",
                             "password": "secret123", "name": "Emma West"})
    assert resp.status_code == 201
    user = resp.get_json()["user"]
    assert user["email"] == "emma@example.com"

    login = client.post("/api/auth/login",
                        json={"username": "emma@example.com", "password": "secret123"})
    assert login.status_code == 200
    assert login.get_json()["user"]["username"] == "emma"


def test_register_rejects_bad_email(client):
    resp = client.post("/api/auth/register",
                       json={"username": "bademail", "email": "not-an-email",
                             "password": "secret123"})
    assert resp.status_code == 400
    assert "email" in resp.get_json()["error"]


def test_register_duplicate_email_rejected(client):
    first = client.post("/api/auth/register",
                        json={"username": "dave", "email": "dave@example.com",
                              "password": "secret123"})
    assert first.status_code == 201
    dup = client.post("/api/auth/register",
                      json={"username": "dave2", "email": "dave@example.com",
                            "password": "secret123"})
    assert dup.status_code == 400
    assert "email" in dup.get_json()["error"]


def test_register_rejects_short_password(client):
    resp = client.post("/api/auth/register",
                       json={"username": "bob", "password": "123"})
    assert resp.status_code == 400
    assert "password" in resp.get_json()["error"]


def test_register_duplicate_username(client):
    client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    dup = client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    assert dup.status_code == 409


def test_login_bad_credentials(client):
    resp = client.post("/api/auth/login",
                       json={"username": "nobody", "password": "wrong"})
    assert resp.status_code == 401


# ------------------------------------------------------------------ risk

def test_evaluate_requires_auth(client):
    resp = client.post("/api/risk/evaluate", json={"customer_id": 1})
    assert resp.status_code == 401


def test_evaluate_unknown_customer(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 9999, "event_type": "transaction",
                             "event": {"amount": 10}},
                       headers=auth_headers)
    assert resp.status_code == 404


def test_evaluate_bad_event_type(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 1, "event_type": "hack",
                             "event": {"amount": 10}},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert "event_type" in resp.get_json()["error"]


def test_evaluate_missing_amount(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 1, "event_type": "transaction", "event": {}},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert any("amount" in k for k in resp.get_json()["error"])


def test_evaluate_allow(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 1, "event_type": "transaction",
                             "event": {"amount": 1000, "txn_type": "transfer",
                                       "city": "Haveri", "device_id": "dev-known"}},
                       headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["decision"] == "ALLOW"
    assert body["event_id"] > 0


def test_step_up_creates_otp_and_verify_flow(client, auth_headers):
    # make the device known first so the only signals are amount + location
    client.post("/api/risk/evaluate",
                json={"customer_id": 2, "event_type": "transaction",
                      "event": {"amount": 500, "city": "Bengaluru", "device_id": "dev-known-2"}},
                headers=auth_headers)

    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 2, "event_type": "transaction",
                             "event": {"amount": 150000, "city": "Delhi",
                                       "device_id": "dev-known-2"}},
                       headers=auth_headers)
    body = resp.get_json()
    assert body["decision"] == "STEP_UP"
    assert body["otp_required"] is True
    txn_id = body["event_id"]

    otp = models.get_latest_otp(txn_id)
    assert otp is not None

    # wrong code rejected
    bad = client.post("/api/otp/verify",
                      json={"transaction_id": txn_id, "code": "000000"},
                      headers=auth_headers)
    assert bad.status_code == 400

    # correct code approves
    good = client.post("/api/otp/verify",
                       json={"transaction_id": txn_id, "code": otp["code"]},
                       headers=auth_headers)
    assert good.status_code == 200
    assert good.get_json()["valid"] is True
    assert models.get_transaction(txn_id)["otp_verified"] == 1

    # replay rejected
    replay = client.post("/api/otp/verify",
                         json={"transaction_id": txn_id, "code": otp["code"]},
                         headers=auth_headers)
    assert replay.status_code == 400


def test_otp_verify_missing_fields(client, auth_headers):
    resp = client.post("/api/otp/verify", json={}, headers=auth_headers)
    assert resp.status_code == 400


# ------------------------------------------------------------------ dashboard / agents

def test_dashboard_summary(client, auth_headers):
    client.post("/api/risk/evaluate",
                json={"customer_id": 3, "event_type": "transaction",
                      "event": {"amount": 1000, "city": "Mysuru", "device_id": "d1"}},
                headers=auth_headers)
    resp = client.get("/api/dashboard/summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(["stats", "transactions", "sim_events", "alerts", "agents", "otps"]).issubset(body)
    assert body["stats"]["total"] >= 1


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/summary").status_code == 401


def test_heartbeat_upsert_and_status(client, auth_headers):
    resp = client.post("/api/agents/heartbeat", json={"agent_name": "agent-x"})
    assert resp.status_code == 200
    summary = client.get("/api/dashboard/summary", headers=auth_headers).get_json()
    agents = {a["agent_name"]: a for a in summary["agents"]}
    assert agents["agent-x"]["status"] == "online"


def test_heartbeat_validation(client):
    assert client.post("/api/agents/heartbeat", json={}).status_code == 400
    assert client.post("/api/agents/heartbeat", json={"agent_name": ""}).status_code == 400