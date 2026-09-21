"""API routes: auth, risk evaluation, OTP verification, dashboard, agent heartbeat.

Every request body is validated and 4xx errors carry a clear {error: {field: msg}}
shape. This layer builds the *enriched* event dict (DB context) that the pure
risk engine consumes, then persists the outcome and raises alerts via the
notifications module — it never contains scoring logic or raw SQL.
"""

import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from backend.api.auth import encode_token, token_required
from backend.db import models
from backend.risk_engine import config
from backend.risk_engine.engine import evaluate_event
from notifications import notifier

bp = Blueprint("api", __name__)

VALID_ROLES = {"analyst", "customer", "admin"}
EVENT_TYPES = {"transaction", "login", "sim_change"}
OTP_TTL_MINUTES = 5


def _is_valid_email(value):
    if not value or "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain


# ---------------------------------------------------------------- helpers

def _utcnow_db():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utcnow_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return None
    return data


def _bad(errors, status=400):
    return jsonify(error=errors), status


def _new_otp_code():
    return f"{secrets.randbelow(1000000):06d}"


def _hours_since(db_timestamp):
    if not db_timestamp:
        return None
    try:
        then = datetime.strptime(db_timestamp, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return max((datetime.now(timezone.utc) - then).total_seconds() / 3600.0, 0.0)
    except ValueError:
        return None


# ---------------------------------------------------------------- auth

@bp.route("/api/auth/register", methods=["POST"])
def register():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)
    errors = {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "analyst").strip()
    name = (data.get("name") or "").strip() or None
    email = (data.get("email") or "").strip().lower()

    if not (3 <= len(username) <= 32) or not username.replace("_", "").isalnum():
        errors["username"] = "Username must be 3-32 alphanumeric characters (underscore allowed)"
    if email:
        if not _is_valid_email(email) or len(email) > 254:
            errors["email"] = "Email must look like name@domain.tld"
        elif models.get_user_by_email(email):
            errors["email"] = "Email already registered"
    if len(password) < 6:
        errors["password"] = "Password must be at least 6 characters"
    if role not in VALID_ROLES:
        errors["role"] = f"role must be one of {sorted(VALID_ROLES)}"
    if errors:
        return _bad(errors)
    if models.get_user_by_username(username):
        return _bad({"username": "Username already taken"}, 409)

    user_id = models.create_user(username, generate_password_hash(password),
                                 role=role, name=name, email=email)
    user = models.get_user_by_id(user_id)
    models.log_audit("auth", "register", user_id,
                     {"username": username, "role": role, "email": email or None})
    return jsonify(token=encode_token(user), user=_public_user(user)), 201


@bp.route("/api/auth/login", methods=["POST"])
def login():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)
    login_identifier = (data.get("username") or data.get("email") or "").strip()
    password = data.get("password") or ""
    user = models.get_user_by_login(login_identifier)
    if user is None or not check_password_hash(user["password_hash"], password):
        return _bad("Invalid email/username or password", 401)
    models.log_audit("auth", "login", user["id"], {"username": user["username"]})
    return jsonify(token=encode_token(user), user=_public_user(user))


def _public_user(user):
    return {"id": user["id"], "username": user["username"],
            "role": user["role"], "name": user["name"], "email": user.get("email")}


# ---------------------------------------------------------------- risk engine

@bp.route("/api/risk/evaluate", methods=["POST"])
@token_required
def risk_evaluate():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)

    customer_id = _to_int(data.get("customer_id"))
    event_type = (data.get("event_type") or "").strip()
    event = data.get("event")
    viewer = g.user

    errors = {}
    if customer_id is None:
        errors["customer_id"] = "customer_id must be an integer"
    elif models.get_customer(customer_id) is None:
        return _bad({"customer_id": "Unknown customer"}, 404)
    if event_type not in EVENT_TYPES:
        errors["event_type"] = f"event_type must be one of {sorted(EVENT_TYPES)}"
    if not isinstance(event, dict):
        errors["event"] = "event must be an object/dict"

    customer = models.get_customer(customer_id) if customer_id else None

    if event_type == "transaction" and isinstance(event, dict):
        amount = event.get("amount")
        try:
            amount_f = float(amount)
        except (TypeError, ValueError):
            amount_f = None
        if amount_f is None or amount_f < 0:
            errors["event.amount"] = "amount is required and must be a non-negative number"

    if errors:
        return _bad(errors)

    rich = dict(event)
    rich["customer_id"] = customer_id
    rich["event_type"] = event_type
    rich["home_city"] = customer["home_city"]

    # DB context for the pure rule engine
    device_id = event.get("device_id")
    rich["is_new_device"] = not models.has_seen_device(customer_id, device_id)
    failed_logins = models.recent_failed_logins(customer_id, config.FAILED_LOGIN_WINDOW_HOURS)
    if event_type == "login" and not event.get("success", True):
        failed_logins += 1
    rich["failed_logins"] = failed_logins

    recent_swaps = models.recent_sim_changes(customer_id, config.SIM_CHANGE_FREQ_WINDOW_HOURS)
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
            customer_id,
            new_sim_id=(event.get("sim_id") or "SIM-CHG-LIVE"),
            device_id=device_id,
            ip_address=event.get("ip_address"),
            risk_score=result["risk_score"],
            decision=result["decision"],
            recorded_at=event_time,
        )
    else:
        event_id = models.create_transaction(
            customer_id,
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
                      "viewer": viewer["username"]})

    alert_id = None
    otp_required = False
    otp_expires_at = None

    if result["decision"] == "BLOCK":
        message = (f"BLOCKED {event_type} #{event_id} for {customer['name']}. "
                   f"Risk {result['risk_score']}. "
                   f"Reasons: {'; '.join(result['reasons']) or 'no specific rule'}")
        alert_id = models.create_alert(
            customer_id, "high", message,
            transaction_id=(None if event_type == "sim_change" else event_id),
            sim_event_id=(event_id if event_type == "sim_change" else None))
        notifier.notify_alert(customer, message)

    elif event_type != "sim_change" and result["decision"] == "STEP_UP":
        code = _new_otp_code()
        expires = (datetime.now(timezone.utc)
                   + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%d %H:%M:%S")
        models.create_otp(event_id, code, expires)
        otp_required = True
        otp_expires_at = (datetime.now(timezone.utc)
                          + timedelta(minutes=OTP_TTL_MINUTES)).strftime("%Y-%m-%dT%H:%M:%SZ")
        message = (f"STEP_UP requested for {event_type} #{event_id} of {customer['name']} "
                   f"(risk {result['risk_score']}). OTP issued.")
        alert_id = models.create_alert(customer_id, "medium", message,
                                       transaction_id=event_id)
        notifier.notify_otp(customer, code, event_id)

    return jsonify(
        event_id=event_id,
        event_type=event_type,
        decision=result["decision"],
        risk_score=result["risk_score"],
        rule_score=result["rule_score"],
        ml_probability=result["ml_probability"],
        reasons=result["reasons"],
        otp_required=otp_required,
        otp_expires_at=otp_expires_at,
        alert_id=alert_id,
    )


# ---------------------------------------------------------------- otp

@bp.route("/api/otp/verify", methods=["POST"])
@token_required
def otp_verify():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)
    transaction_id = _to_int(data.get("transaction_id"))
    code = str(data.get("code") or "").strip()

    errors = {}
    if transaction_id is None:
        errors["transaction_id"] = "transaction_id must be an integer"
    if not code:
        errors["code"] = "code is required"
    if errors:
        return _bad(errors)

    txn = models.get_transaction(transaction_id)
    if txn is None:
        return _bad({"transaction_id": "Unknown transaction"}, 404)
    otp = models.get_latest_otp(transaction_id)
    if otp is None:
        return _bad("No OTP was issued for this transaction", 404)
    if otp["used"]:
        return _bad("OTP has already been used", 400)
    if _utcnow_db() > otp["expires_at"]:
        return _bad("OTP has expired", 400)
    if otp["code"] != code:
        return _bad("Invalid OTP code", 400)

    models.mark_otp_used(otp["id"])
    models.mark_otp_verified(transaction_id)
    models.log_audit("otp", "verified", transaction_id,
                     {"viewer": g.user["username"], "otp_id": otp["id"]})

    return jsonify(valid=True, message="OTP verified, transaction approved",
                   transaction_id=transaction_id)


# ---------------------------------------------------------------- dashboard

@bp.route("/api/dashboard/summary", methods=["GET"])
@token_required
def dashboard_summary():
    agents = models.list_agents()
    now = datetime.now(timezone.utc)
    enriched_agents = []
    for a in agents:
        try:
            last = datetime.strptime(a["last_heartbeat"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            status = "online" if (now - last).total_seconds() <= 60 else "stale"
        except ValueError:
            status = "stale"
        enriched_agents.append({**a, "status": status})

    return jsonify(
        stats={
            **models.transaction_counts(),
            "alerts": len(models.list_alerts()),
            "customers": len(models.list_customers()),
            "agents": len(agents),
        },
        transactions=models.list_transactions(100),
        sim_events=models.list_sim_events(50),
        alerts=models.list_alerts(100),
        agents=enriched_agents,
        otps=models.pending_otps(20),
    )


# ---------------------------------------------------------------- agents

@bp.route("/api/agents/heartbeat", methods=["POST"])
def agent_heartbeat():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)
    agent_name = (data.get("agent_name") or "").strip()
    if not agent_name or len(agent_name) > 64:
        return _bad({"agent_name": "agent_name must be a non-empty string (max 64 chars)"})
    models.upsert_heartbeat(agent_name)
    models.log_audit("agent", "heartbeat", None, {"agent_name": agent_name})
    return jsonify(status="ok", agent_name=agent_name, received_at=_utcnow_iso())