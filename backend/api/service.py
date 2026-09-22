"""Risk evaluation orchestration shared by the API route and the demo generator.

This is the compiled version of the /api/risk/evaluate flow: enrich the event
with DB context, run the pure risk engine, persist the outcome, raise alerts,
and (for STEP_UP) issue an OTP. It has no Flask request context so it can be
driven by both an authenticated API call and the autonomous demo traffic
generator without duplicating logic.
"""

import secrets
from datetime import datetime, timedelta, timezone

from backend.db import models
from backend.risk_engine import config
from backend.risk_engine.engine import evaluate_event
from notifications import notifier

EVENT_TYPES = {"transaction", "login", "sim_change"}
OTP_TTL_MINUTES = 5


def _utcnow_db():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours_since(db_timestamp):
    if not db_timestamp:
        return None
    try:
        then = datetime.strptime(db_timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - then).total_seconds() / 3600.0, 0.0)
    except ValueError:
        return None


def validate_event_request(event_type, event):
    """Validate the raw request. Returns {field: message} (empty when valid)."""
    errors = {}
    if event_type not in EVENT_TYPES:
        errors["event_type"] = f"event_type must be one of {sorted(EVENT_TYPES)}"
    if not isinstance(event, dict):
        errors["event"] = "event must be an object/dict"
    if event_type == "transaction" and isinstance(event, dict):
        try:
            amount = float(event.get("amount"))
        except (TypeError, ValueError):
            amount = None
        if amount is None or amount < 0:
            errors["event.amount"] = "amount is required and must be a non-negative number"
    return errors


def evaluate_and_store(customer, event_type, event, viewer=None):
    """Enrich, score, persist, and alert. Returns the full API response dict.

    `customer` is the owning customer dict (with at least id/name/home_city).
    """
    rich = dict(event)
    rich["customer_id"] = customer["id"]
    rich["event_type"] = event_type
    rich["home_city"] = customer.get("home_city")

    device_id = event.get("device_id")
    rich["is_new_device"] = not models.has_seen_device(customer["id"], device_id)
    failed_logins = models.recent_failed_logins(
        customer["id"], config.FAILED_LOGIN_WINDOW_HOURS)
    if event_type == "login" and not event.get("success", True):
        failed_logins += 1
    rich["failed_logins"] = failed_logins

    recent_swaps = models.recent_sim_changes(
        customer["id"], config.SIM_CHANGE_FREQ_WINDOW_HOURS)
    rich["sim_changes_recent"] = len(recent_swaps)
    rich["hours_since_sim_change"] = (
        _hours_since(recent_swaps[0]["recorded_at"]) if recent_swaps
        else (0.0 if event_type == "sim_change" else None)
    )

    result = evaluate_event(rich)

    event_time = event.get("timestamp") or _utcnow_iso()
    success = 0 if (event_type == "login" and not event.get("success", True)) else 1
    amount = event.get("amount")
    if amount is not None:
        try:
            amount = float(amount)
        except (TypeError, ValueError):
            amount = None

    if event_type == "sim_change":
        event_id = models.create_sim_event(
            customer["id"],
            new_sim_id=(event.get("sim_id") or "SIM-CHG-LIVE"),
            device_id=device_id,
            ip_address=event.get("ip_address"),
            risk_score=result["risk_score"],
            decision=result["decision"],
            recorded_at=event_time,
        )
    else:
        event_id = models.create_transaction(
            customer["id"],
            txn_type=(event.get("txn_type") or ("transfer" if event_type == "transaction" else "login")),
            amount=amount,
            currency=(event.get("currency") or "INR"),
            channel=event.get("channel"),
            device_id=device_id,
            ip_address=event.get("ip_address"),
            city=event.get("city"),
            event_time=event_time,
            risk_score=result["risk_score"],
            rule_score=result["rule_score"],
            ml_probability=result["ml_probability"],
            decision=result["decision"],
            reasons=result["reasons"],
            success=success,
        )

    models.log_audit(event_type, "evaluated", event_id,
                     {"decision": result["decision"], "risk_score": result["risk_score"],
                      "viewer": viewer or "system"})

    alert_id = None
    otp_required = False
    otp_expires_at = None

    if result["decision"] == "BLOCK":
        message = (f"BLOCKED {event_type} #{event_id} for {customer['name']}. "
                   f"Risk {result['risk_score']}. "
                   f"Reasons: {'; '.join(result['reasons']) or 'no specific rule'}")
        alert_id = models.create_alert(
            customer["id"], "high", message,
            transaction_id=(None if event_type == "sim_change" else event_id),
            sim_event_id=(event_id if event_type == "sim_change" else None))
        notifier.notify_alert(customer, message)

    elif event_type != "sim_change" and result["decision"] == "STEP_UP":
        code = f"{secrets.randbelow(1000000):06d}"
        expires = (datetime.now(timezone.utc)
                   + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        models.create_otp(event_id, code, expires)
        otp_required = True
        otp_expires_at = (datetime.now(timezone.utc)
                          + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = (f"STEP_UP requested for {event_type} #{event_id} of {customer['name']} "
                   f"(risk {result['risk_score']}). OTP issued.")
        alert_id = models.create_alert(customer["id"], "medium", message,
                                       transaction_id=event_id)
        notifier.notify_otp(customer, code, event_id)

    return {
        "event_id": event_id,
        "event_type": event_type,
        "decision": result["decision"],
        "risk_score": result["risk_score"],
        "rule_score": result["rule_score"],
        "ml_probability": result["ml_probability"],
        "reasons": result["reasons"],
        "otp_required": otp_required,
        "otp_expires_at": otp_expires_at,
        "alert_id": alert_id,
    }