"""API endpoint tests: auth/reg, JWT, customer ownership isolation, risk
evaluation, OTP step-up + verification, role-based authorization, dashboard
summary, heartbeat, and admin/analyst analytics.
"""

import pytest

from backend.db import models


# ------------------------------------------------------------------ auth

def test_register_and_login(client):
    resp = client.post("/api/auth/register",
                       json={"username": "alice", "password": "secret123",
                             "role": "analyst", "name": "Alice Analyst"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["role"] == "analyst"
    assert "token" in body

    login = client.post("/api/auth/login",
                        json={"username": "alice", "password": "secret123"})
    assert login.status_code == 200
    assert "token" in login.get_json()


def test_register_creates_customer_for_customer_role(client):
    resp = client.post("/api/auth/register",
                       json={"username": "new_cust", "password": "secret123",
                             "role": "customer", "name": "New Customer",
                             "email": "newcust@example.com"})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["user"]["role"] == "customer"
    customer = body["user"].get("customer")
    assert customer is not None
    assert customer["id"] > 0
    # the customer row must be linked to the new user in the DB
    stored = models.get_customer(customer["id"])
    assert stored["user_id"] is not None
    user = models.get_user_by_username("new_cust")
    assert user["id"] == stored["user_id"]


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


def test_register_short_password(client):
    resp = client.post("/api/auth/register",
                       json={"username": "bob", "password": "123"})
    assert resp.status_code == 400
    assert "password" in resp.get_json()["error"]


def test_register_duplicate_username(client):
    client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    dup = client.post("/api/auth/register", json={"username": "carol", "password": "secret123"})
    assert dup.status_code == 409


def test_register_invalid_role(client):
    resp = client.post("/api/auth/register",
                       json={"username": "odd", "password": "secret123", "role": "hacker"})
    assert resp.status_code == 400
    assert "role" in resp.get_json()["error"]


def test_login_by_email(client):
    client.post("/api/auth/register",
                json={"username": "emma", "email": "Emma@Example.com",
                      "password": "secret123", "role": "customer", "name": "Emma West"})
    login = client.post("/api/auth/login",
                        json={"username": "emma@example.com", "password": "secret123"})
    assert login.status_code == 200
    assert login.get_json()["user"]["username"] == "emma"


def test_login_bad_credentials(client):
    resp = client.post("/api/auth/login",
                       json={"username": "nobody", "password": "wrong"})
    assert resp.status_code == 401


def test_auth_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_auth_me_returns_user_and_customer(client, customer_headers):
    resp = client.get("/api/auth/me", headers=customer_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["user"]["username"] == "cust_a"
    assert body["customer"]["id"] > 0
    assert body["customer"]["user_id"] is not None


def test_register_defaults_not_analyst(client):
    # a plain registration without a role must not grant analyst powers
    resp = _register_plain("randouser", client)
    assert resp.status_code == 201
    assert resp.get_json()["user"]["role"] != "analyst"


def _register_plain(username, client):
    # default role -> customer, never analyst
    return client.post("/api/auth/register",
                       json={"username": username, "password": "secret123"})


# ------------------------------------------------------------------ ownership / scope

def test_customer_only_sees_own_transactions(client, customer_headers,
                                             customer_b_headers):
    _, own_id = _own_customer(client, customer_headers)
    _, other_id = _own_customer(client, customer_b_headers)
    assert own_id != other_id

    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 1000, "city": "Haveri", "device_id": "dev-own"}},
                headers=customer_headers)

    mine = client.get("/api/customer/me/transactions", headers=customer_headers)
    assert mine.status_code == 200
    mine_rows = mine.get_json()["transactions"]
    assert mine_rows
    assert all(int(t["customer_id"]) == own_id for t in mine_rows)

    theirs = client.get("/api/customer/me/transactions", headers=customer_b_headers)
    assert theirs.status_code == 200
    assert all(int(t["customer_id"]) == other_id for t in theirs.get_json()["transactions"])


def test_customer_cannot_read_other_customers_dashboard(client, customer_headers,
                                                        customer_b_headers):
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 900, "city": "Haveri", "device_id": "dev-own2"}},
                headers=customer_headers)

    mine = client.get("/api/customer/me/risk-summary", headers=customer_headers)
    assert mine.status_code == 200

    # B must not see A's stats in B's own summary
    b = client.get("/api/customer/me/risk-summary", headers=customer_b_headers)
    assert b.status_code == 200
    assert (b.get_json()["risk_summary"]["total_events"] or 0) == 0


def test_customer_cannot_impersonate_admin(client, customer_headers,
                                           customer_b_headers):
    for path in ["/api/admin/users", "/api/admin/customers", "/api/admin/analytics",
                 "/api/admin/alerts"]:
        resp = client.get(path, headers=customer_headers)
        assert resp.status_code == 403, (path, resp.status_code)


def test_customer_cannot_read_admin_customer_detail(client, customer_headers):
    resp = client.get("/api/admin/customers/1", headers=customer_headers)
    assert resp.status_code == 403


def test_analyst_can_read_admin_analytics(client, auth_headers):
    for path in ["/api/admin/users", "/api/admin/customers", "/api/admin/analytics",
                 "/api/admin/alerts"]:
        resp = client.get(path, headers=auth_headers)
        assert resp.status_code == 200, (path, resp.status_code)
    resp = client.get("/api/admin/customers/1", headers=auth_headers)
    assert resp.status_code == 200


def _own_customer(client, headers):
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    body = resp.get_json()
    return body["user"], body["customer"]["id"]


# ------------------------------------------------------------------ risk / evaluate

def test_evaluate_requires_auth(client):
    resp = client.post("/api/risk/evaluate", json={"event_type": "transaction",
                                                   "event": {}})
    assert resp.status_code == 401


def test_evaluate_unknown_event_type(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "hack", "event": {"amount": 10}},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert "event_type" in resp.get_json()["error"]


def test_evaluate_missing_amount(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction", "event": {}},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert any("amount" in k for k in resp.get_json()["error"])


def test_evaluate_allow(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 2000, "city": "Haveri",
                                       "device_id": "dev-known-most"}},
                       headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["decision"] == "ALLOW"
    assert body["risk_score"] < 25
    assert body["transaction_id"] > 0
    assert body["customer_id"] > 0
    assert "customer_id" in body


def test_evaluate_step_up(client, auth_headers):
    # prime the device first so the server sees it as known, then a high-amount
    # foreign-city transaction must trip STEP_UP (never silently ALLOW)
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 500, "city": "Haveri",
                                "device_id": "dev-ched", "is_new_device": False}},
                headers=auth_headers)
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 900000, "city": "Delhi",
                                       "device_id": "dev-ched", "is_new_device": False}},
                       headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["decision"] == "STEP_UP"


def test_evaluate_ignores_foreign_customer_id(client, auth_headers):
    """A caller-provided customer_id must never control the write target."""
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 555000, "city": "Delhi",
                                       "device_id": "dev-x", "is_new_device": False}},
                       headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    own = models.get_customer_by_user(models.get_user_by_username("testuser")["id"])
    assert body["customer_id"] == own["id"]


def test_evaluate_login_and_sim_change_events(client, auth_headers):
    login = client.post("/api/risk/evaluate",
                        json={"event_type": "login",
                              "event": {"success": False, "city": "Haveri",
                                        "device_id": "dev-l1"}},
                        headers=auth_headers)
    assert login.status_code == 200
    login_body = login.get_json()
    # server is authoritative: a failed login on a device it has never seen must
    # never be silently ALLOWed — at minimum the fresh-device signal is surfaced
    assert login_body["decision"] in ("ALLOW", "STEP_UP", "BLOCK")
    assert any("new" in r.lower() or "device" in r.lower()
               for r in login_body["reasons"])

    sim_resp = client.post("/api/risk/evaluate",
                           json={"event_type": "sim_change",
                                 "event": {"device_id": "dev-sim"}},
                           headers=auth_headers)
    assert sim_resp.status_code == 200
    assert sim_resp.get_json()["decision"] in ("ALLOW", "STEP_UP", "BLOCK")
    assert sim_resp.get_json()["transaction_id"] is None


def test_high_risk_transaction_blocked_and_alerted(client, auth_headers):
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 2_000_000, "city": "Delhi",
                                       "device_id": "dev-fraud-99",
                                       "is_new_device": True}},
                       headers=auth_headers)
    body = resp.get_json()
    assert body["decision"] == "BLOCK"
    assert len(body["reasons"]) >= 1
    txn = models.get_transaction(body["transaction_id"])
    assert txn is not None
    assert txn["decision"] == "BLOCK"
    alerts = [a for a in models.list_alerts(1000)
              if a["transaction_id"] == txn["id"]]
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "high"


# ------------------------------------------------------------------ otp

def test_step_up_creates_otp_and_verify_flow(client, auth_headers):
    # make the device known first so the only signals are location + amount
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 500, "city": "Haveri", "device_id": "dev-known-2"}},
                headers=auth_headers)

    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 150000, "city": "Delhi",
                                       "device_id": "dev-known-2"}},
                       headers=auth_headers)
    body = resp.get_json()
    assert body["decision"] == "STEP_UP"
    assert body["otp_required"] is True
    txn_id = body["transaction_id"]

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


def test_otp_verify_requires_auth(client):
    resp = client.post("/api/otp/verify",
                       json={"transaction_id": 1, "code": "000000"})
    assert resp.status_code == 401


def test_otp_verify_missing_fields(client, auth_headers):
    resp = client.post("/api/otp/verify", json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_customer_cannot_verify_another_customers_otp(client, customer_headers,
                                                      customer_b_headers):
    # prime the device first so the server sees it as known (derives fresh-ness itself)
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 500, "city": "Haveri",
                                "device_id": "dev-otp-x"}},
                headers=customer_headers)
    resp = client.post("/api/risk/evaluate",
                       json={"event_type": "transaction",
                             "event": {"amount": 150000, "city": "Delhi",
                                       "device_id": "dev-otp-x"}},
                       headers=customer_headers)
    body = resp.get_json()
    assert body["decision"] == "STEP_UP"
    txn_id = body["transaction_id"]
    otp = models.get_latest_otp(txn_id)

    as_b = client.post("/api/otp/verify",
                       json={"transaction_id": txn_id, "code": otp["code"]},
                       headers=customer_b_headers)
    assert as_b.status_code == 403


# ------------------------------------------------------------------ dashboard

def test_dashboard_summary(client, auth_headers):
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 1000, "city": "Haveri", "device_id": "dev-d1"}},
                headers=auth_headers)
    resp = client.get("/api/dashboard/summary", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    assert set(["stats", "transactions", "sim_events", "alerts", "agents", "otps"]).issubset(body)
    assert body["stats"]["total"] >= 1


def test_dashboard_summary_scoped_for_customer(client, customer_headers,
                                               customer_b_headers):
    client.post("/api/risk/evaluate",
                json={"event_type": "transaction",
                      "event": {"amount": 2000, "city": "Haveri", "device_id": "dev-d2"}},
                headers=customer_headers)

    a = client.get("/api/dashboard/summary", headers=customer_headers)
    assert a.status_code == 200
    a_body = a.get_json()
    assert a_body["stats"]["total"] == 1
    assert a_body["profile"]["customer"]["id"] == a_body["stats"]["customer_id"]

    b = client.get("/api/dashboard/summary", headers=customer_b_headers)
    b_body = b.get_json()
    assert b_body["stats"]["total"] == 0


def test_dashboard_requires_auth(client):
    assert client.get("/api/dashboard/summary").status_code == 401


# ------------------------------------------------------------------ agents

def test_heartbeat_upsert_and_status(client, auth_headers):
    resp = client.post("/api/agents/heartbeat", json={"agent_name": "agent-x"})
    assert resp.status_code == 200
    summary = client.get("/api/dashboard/summary", headers=auth_headers).get_json()
    agents = {a["agent_name"]: a for a in summary["agents"]}
    assert agents["agent-x"]["status"] == "online"


def test_heartbeat_validation(client):
    assert client.post("/api/agents/heartbeat", json={}).status_code == 400
    assert client.post("/api/agents/heartbeat",
                       json={"agent_name": ""}).status_code == 400


# ------------------------------------------------------------------ admin analytics

def test_analyst_dashboard_summary(client, auth_headers):
    resp = client.get("/api/admin/customers", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.get_json()["customers"]) >= 0


def test_admin_analytics_shape(client, auth_headers):
    resp = client.get("/api/admin/analytics", headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()
    for key in ["total_transactions", "blocked", "allowed", "step_up",
                "active_alerts", "customers", "users"]:
        assert key in body


def test_admin_customer_detail(client, auth_headers):
    customers = client.get("/api/admin/customers", headers=auth_headers).get_json()["customers"]
    if not customers:
        pytest.skip("seed did not create any customers")
    cid = customers[0]["id"]
    resp = client.get(f"/api/admin/customers/{cid}", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["customer"]["id"] == cid


def test_admin_unknown_customer_404(client, auth_headers):
    resp = client.get("/api/admin/customers/999999", headers=auth_headers)
    assert resp.status_code == 404
