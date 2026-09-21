"""End-to-end demo flow.

Registers a user, submits a high-risk transaction, confirms it is BLOCKed and
that an alert row exists; then drives a STEP_UP transaction through OTP
verification to confirm the step-up unlocks it.
"""

from backend.db import models


def test_high_risk_transaction_is_blocked_and_alerted(client, auth_headers):
    # 1. register happened in the auth_headers fixture
    # 2. submit a high-risk transaction (big amount, new device, foreign city)
    resp = client.post("/api/risk/evaluate",
                       json={
                           "customer_id": 1,
                           "event_type": "transaction",
                           "event": {
                               "amount": 2_000_000,
                               "txn_type": "transfer",
                               "channel": "mobile",
                               "city": "Delhi",
                               "device_id": "dev-fraud-999",
                               "ip_address": "9.9.9.9",
                           },
                       },
                       headers=auth_headers)
    assert resp.status_code == 200
    body = resp.get_json()

    # 3. it must be BLOCKed with at least one human-readable reason
    assert body["decision"] == "BLOCK"
    assert len(body["reasons"]) >= 1
    assert body["alert_id"]

    # 4. transaction persisted with BLOCK
    txn = models.get_transaction(body["event_id"])
    assert txn is not None
    assert txn["decision"] == "BLOCK"
    assert txn["reasons_json"]

    # 5. an alert row exists for this transaction
    alerts = models.list_alerts()
    matching = [a for a in alerts if a["transaction_id"] == txn["id"]]
    assert len(matching) == 1
    assert matching[0]["severity"] == "high"

    # 6. dashboard reflects the block
    summary = client.get("/api/dashboard/summary", headers=auth_headers).get_json()
    assert summary["stats"]["BLOCK"] >= 1
    assert any(t["id"] == txn["id"] for t in summary["transactions"])


def test_step_up_otp_unlocks_transaction(client, auth_headers):
    # make device known so only amount + location trigger
    client.post("/api/risk/evaluate",
                json={"customer_id": 4, "event_type": "transaction",
                      "event": {"amount": 400, "city": "Hubballi", "device_id": "dev-e2e"}},
                headers=auth_headers)

    resp = client.post("/api/risk/evaluate",
                       json={"customer_id": 4, "event_type": "transaction",
                             "event": {"amount": 500000, "city": "Chennai",
                                       "device_id": "dev-e2e"}},
                       headers=auth_headers)
    body = resp.get_json()
    assert body["decision"] == "STEP_UP"
    assert body["otp_required"] is True

    txn_id = body["event_id"]
    code = models.get_latest_otp(txn_id)["code"]
    verify = client.post("/api/otp/verify",
                         json={"transaction_id": txn_id, "code": code},
                         headers=auth_headers)
    assert verify.status_code == 200
    assert models.get_transaction(txn_id)["otp_verified"] == 1