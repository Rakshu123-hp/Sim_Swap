"""API routes: auth, customer data, risk evaluation, OTP verification, dashboard,
analyst/admin analytics, and agent heartbeat.

Every request body is validated and 4xx errors carry a clear {error: {field: msg}}
shape. Customer-scoped endpoints always resolve the customer from the authenticated
JWT user (never from the request body), so one user can never read another
customer's data. Scoring logic lives in backend.risk_engine and orchestration in
backend.api.service.
"""

from datetime import datetime, timezone

from flask import Blueprint, g, jsonify, request
from werkzeug.security import check_password_hash, generate_password_hash

from backend.api.auth import encode_token, role_required, token_required
from backend.api.service import evaluate_and_store, validate_event_request
from backend.db import models

bp = Blueprint("api", __name__)

VALID_ROLES = {"analyst", "customer", "admin"}
OTP_TTL_MINUTES = 5


def _is_valid_email(value):
    if not value or "@" not in value:
        return False
    local, _, domain = value.partition("@")
    return bool(local) and "." in domain


# ---------------------------------------------------------------- helpers

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


def _user_customer():
    """Resolve (creates if needed) the customer attached to the JWT user."""
    return models.get_or_create_customer_for_user(g.user)


def _customer_payload(customer):
    if not customer:
        return None
    return {
        "id": customer["id"],
        "user_id": customer.get("user_id"),
        "name": customer["name"],
        "email": customer.get("email"),
        "phone": customer.get("phone"),
        "home_city": customer.get("home_city"),
        "status": customer.get("status") or "active",
        "created_at": customer.get("created_at"),
    }


def _public_user(user):
    customer = models.get_customer_by_user(user["id"])
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "name": user["name"],
        "email": user.get("email"),
        "created_at": user.get("created_at"),
        "customer": _customer_payload(customer),
    }


# ---------------------------------------------------------------- auth

@bp.route("/api/auth/register", methods=["POST"])
def register():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)
    errors = {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    role = (data.get("role") or "customer").strip()
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
    customer = models.get_or_create_customer_for_user(user)
    models.touch_user(user_id)
    models.log_audit("auth", "register", user_id,
                     {"username": username, "role": role, "email": email or None})
    return jsonify(token=encode_token(user), user=_public_user(user),
                   customer=_customer_payload(customer)), 201


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
    customer = models.get_or_create_customer_for_user(user)
    models.touch_user(user["id"])
    models.log_audit("auth", "login", user["id"], {"username": user["username"]})
    return jsonify(token=encode_token(user), user=_public_user(user),
                   customer=_customer_payload(customer))


@bp.route("/api/auth/me", methods=["GET"])
@token_required
def auth_me():
    customer = _user_customer()
    return jsonify(user=_public_user(g.user), customer=_customer_payload(customer))


# ---------------------------------------------------------------- customer profile

@bp.route("/api/customer/me", methods=["GET"])
@token_required
def customer_me():
    customer = _user_customer()
    return jsonify(customer=_customer_payload(customer),
                   stats=models.customer_stats(customer["id"]))


@bp.route("/api/customer/me/transactions", methods=["GET"])
@token_required
def customer_me_transactions():
    customer = _user_customer()
    return jsonify(customer_id=customer["id"],
                   transactions=models.list_transactions(100, customer["id"]))


@bp.route("/api/customer/me/logins", methods=["GET"])
@token_required
def customer_me_logins():
    customer = _user_customer()
    return jsonify(customer_id=customer["id"],
                   logins=models.list_login_events(100, customer["id"]))


@bp.route("/api/customer/me/sim-changes", methods=["GET"])
@token_required
def customer_me_sim_changes():
    customer = _user_customer()
    return jsonify(customer_id=customer["id"],
                   sim_events=models.list_sim_events(100, customer["id"]))


@bp.route("/api/customer/me/alerts", methods=["GET"])
@token_required
def customer_me_alerts():
    customer = _user_customer()
    return jsonify(customer_id=customer["id"],
                   alerts=models.list_alerts(100, customer["id"]))


@bp.route("/api/customer/me/risk-summary", methods=["GET"])
@token_required
def customer_me_risk_summary():
    customer = _user_customer()
    return jsonify(customer_id=customer["id"],
                   risk_summary=models.risk_summary(customer["id"]))


# ---------------------------------------------------------------- risk engine

@bp.route("/api/risk/evaluate", methods=["POST"])
@token_required
def risk_evaluate():
    data = _json_body()
    if data is None:
        return _bad("Request body must be valid JSON", 400)

    event_type = (data.get("event_type") or "").strip()
    event = data.get("event")
    customer = _user_customer()

    errors = validate_event_request(event_type, event)
    if errors:
        return _bad(errors)

    result = evaluate_and_store(customer, event_type, event, viewer=g.user["username"])
    result["customer_id"] = customer["id"]
    result["transaction_id"] = result["event_id"] if event_type != "sim_change" else None
    return jsonify(result)


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

    if g.user["role"] == "customer":
        customer = _user_customer()
        if txn["customer_id"] != customer["id"]:
            return _bad("You can only verify OTPs for your own transactions", 403)

    otp = models.get_latest_otp(transaction_id)
    if otp is None:
        return _bad("No OTP was issued for this transaction", 404)
    if otp["used"]:
        return _bad("OTP has already been used", 400)
    try:
        _expires = datetime.strptime(otp["expires_at"], "%Y-%m-%d %H:%M:%S")
        _expires = _expires.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return _bad("OTP has an invalid expiry", 400)
    if datetime.now(timezone.utc) > _expires:
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
    is_customer_view = g.user["role"] == "customer"
    customer = _user_customer() if is_customer_view else None
    customer_id = customer["id"] if customer else None

    stats = models.transaction_counts(customer_id)
    stats["customer_id"] = customer_id
    if customer_id is not None:
        cstats = models.customer_stats(customer_id)
        stats.update(alerts=cstats["alerts"], login_attempts=cstats["login_attempts"],
                     sim_changes=cstats["sim_changes"])
    else:
        stats.update(alerts=len(models.list_alerts(1000, None)),
                     customers=len(models.list_customers()))

    if is_customer_view:
        agents = []
        agents_online = 0
    else:
        agents = models.list_agents()
        agents_online = sum(
            1 for a in _with_agent_status(agents) if a["status"] == "online")
        agents = _with_agent_status(agents)

    return jsonify(
        profile={
            **(_public_user(g.user)),
            "customer": _customer_payload(customer),
        },
        stats=stats,
        transactions=models.list_transactions(100, customer_id),
        logins=models.list_login_events(50, customer_id),
        sim_events=models.list_sim_events(50, customer_id),
        alerts=models.list_alerts(100, customer_id),
        agents=agents,
        agents_online=agents_online,
        otps=models.pending_otps(20, customer_id),
        risk_summary=models.risk_summary(customer_id) if customer_id else None,
        last_updated=_utcnow_iso(),
    )


def _with_agent_status(agents):
    now = datetime.now(timezone.utc)
    out = []
    for a in agents:
        try:
            last = datetime.strptime(a["last_heartbeat"], "%Y-%m-%d %H:%M:%S").replace(
                tzinfo=timezone.utc)
            status = "online" if (now - last).total_seconds() <= 60 else "stale"
        except ValueError:
            status = "stale"
        out.append({**a, "status": status})
    return out


# ---------------------------------------------------------------- analyst / admin

@bp.route("/api/admin/users", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_users():
    return jsonify(users=models.list_users())


@bp.route("/api/admin/customers", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_customers():
    return jsonify(customers=models.list_customers())


@bp.route("/api/admin/customers/<int:customer_id>", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_customer_detail(customer_id):
    customer = models.get_customer(customer_id)
    if customer is None:
        return _bad({"customer_id": "Unknown customer"}, 404)
    user = models.get_user_by_id(customer["user_id"]) if customer.get("user_id") else None
    return jsonify(
        customer=_customer_payload(customer),
        owner={"username": user["username"], "role": user["role"],
               "email": user.get("email"), "created_at": user.get("created_at")} if user else None,
        stats=models.customer_stats(customer_id),
        risk_summary=models.risk_summary(customer_id),
        transactions=models.list_transactions(100, customer_id),
        logins=models.list_login_events(50, customer_id),
        sim_events=models.list_sim_events(50, customer_id),
        alerts=models.list_alerts(100, customer_id),
    )


@bp.route("/api/admin/customers/<int:customer_id>/transactions", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_customer_transactions(customer_id):
    if models.get_customer(customer_id) is None:
        return _bad({"customer_id": "Unknown customer"}, 404)
    return jsonify(customer_id=customer_id,
                   transactions=models.list_transactions(200, customer_id))


@bp.route("/api/admin/customers/<int:customer_id>/risk", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_customer_risk(customer_id):
    if models.get_customer(customer_id) is None:
        return _bad({"customer_id": "Unknown customer"}, 404)
    return jsonify(customer_id=customer_id,
                   risk_summary=models.risk_summary(customer_id),
                   stats=models.customer_stats(customer_id))


@bp.route("/api/admin/alerts", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_alerts():
    return jsonify(alerts=models.list_alerts(500, None))


@bp.route("/api/admin/analytics", methods=["GET"])
@token_required
@role_required("analyst", "admin")
def admin_analytics():
    analytics = models.analytics()
    analytics["users"] = models.count_users()
    analytics["customers"] = models.count_customers()
    return jsonify(analytics)


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