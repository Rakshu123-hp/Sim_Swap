"""Thin data-access layer for SQLite.

Business logic lives nowhere in this module: it only maps calls to rows.
The risk engine and API never open a connection directly; they go through here.
"""

import json
import os
import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
_REPO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_DATABASE_URL = "sqlite:///backend/db/simswap.db"


def database_path():
    url = os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    if url.startswith("sqlite:///"):
        path = url[len("sqlite:///"):]
    else:
        path = url
    p = Path(path)
    if not p.is_absolute():
        p = _REPO_ROOT / p
    return str(p)


def get_db():
    conn = sqlite3.connect(database_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables from schema.sql. Safe to call repeatedly."""
    with open(_SCHEMA_PATH, "r", encoding="utf-8") as fh:
        schema = fh.read()
    conn = get_db()
    try:
        conn.executescript(schema)
        _ensure_column(conn, "users", "email", "ALTER TABLE users ADD COLUMN email TEXT")
        conn.commit()
    finally:
        conn.close()


def _ensure_column(conn, table, column, alter_sql):
    cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(alter_sql)


# --------------------------------------------------------------------------- users

def create_user(username, password_hash, role="analyst", name=None, email=None):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, role, name) VALUES (?, ?, ?, ?, ?)",
            (username, email, password_hash, role, name),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_user_by_username(username):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email):
    if not email:
        return None
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_login(login):
    """Resolve a login that is either a username or an email (case-insensitive)."""
    if not login:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE username = ? "
            "OR (email IS NOT NULL AND email = ?) LIMIT 1",
            (login, login.lower()),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ----------------------------------------------------------------------- customers

def create_customer(name, phone=None, email=None, home_city=None):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO customers (name, phone, email, home_city) VALUES (?, ?, ?, ?)",
            (name, phone, email, home_city),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_customer(customer_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_customers():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM customers ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------- sim_events

def create_sim_event(customer_id, new_sim_id, device_id=None, ip_address=None,
                     risk_score=None, decision=None, recorded_at=None):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO sim_events (customer_id, new_sim_id, device_id, ip_address, "
            "risk_score, decision, recorded_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (customer_id, new_sim_id, device_id, ip_address, risk_score, decision, recorded_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_sim_events(limit=25):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT s.*, c.name AS customer_name FROM sim_events s "
            "LEFT JOIN customers c ON c.id = s.customer_id "
            "ORDER BY s.recorded_at DESC, s.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def recent_sim_changes(customer_id, hours=24):
    """SIM-change events for a customer in the last `hours` hours."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM sim_events WHERE customer_id = ? "
            "AND datetime(recorded_at) >= datetime('now', ?) ORDER BY recorded_at DESC",
            (customer_id, "-%d hours" % hours),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def has_seen_device(customer_id, device_id):
    """True if this device already appears for the customer (txns or sim events)."""
    if not device_id:
        return True
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT 1 FROM transactions WHERE customer_id = ? AND device_id = ? "
            "UNION SELECT 1 FROM sim_events WHERE customer_id = ? AND device_id = ? LIMIT 1",
            (customer_id, device_id, customer_id, device_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def recent_failed_logins(customer_id, hours=24):
    """Count failed login events for a customer in the last `hours` hours."""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE customer_id = ? "
            "AND txn_type = 'login' AND success = 0 "
            "AND datetime(created_at) >= datetime('now', ?)",
            (customer_id, "-%d hours" % hours),
        ).fetchone()
        return int(row["n"])
    finally:
        conn.close()


# --------------------------------------------------------------------- transactions

def create_transaction(customer_id, txn_type, amount=None, currency="INR", channel=None,
                       device_id=None, ip_address=None, city=None, event_time=None,
                       risk_score=None, rule_score=None, ml_probability=None,
                       decision="ALLOW", reasons=None, success=1):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO transactions (customer_id, amount, currency, txn_type, channel, "
            "device_id, ip_address, city, event_time, risk_score, rule_score, "
            "ml_probability, decision, reasons_json, success) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (customer_id, amount, currency, txn_type, channel, device_id, ip_address, city,
             event_time, risk_score, rule_score, ml_probability, decision,
             json.dumps(reasons) if reasons else None, success),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_transaction(transaction_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM transactions WHERE id = ?", (transaction_id,)).fetchone()
        out = dict(row) if row else None
        if out and out.get("reasons_json"):
            try:
                out["reasons"] = json.loads(out["reasons_json"])
            except (TypeError, ValueError):
                out["reasons"] = []
        return out
    finally:
        conn.close()


def mark_otp_verified(transaction_id):
    conn = get_db()
    try:
        conn.execute("UPDATE transactions SET otp_verified = 1 WHERE id = ?", (transaction_id,))
        conn.commit()
    finally:
        conn.close()


def list_transactions(limit=25):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT t.*, c.name AS customer_name FROM transactions t "
            "LEFT JOIN customers c ON c.id = t.customer_id "
            "ORDER BY t.created_at DESC, t.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["reasons"] = json.loads(d["reasons_json"]) if d.get("reasons_json") else []
            except (TypeError, ValueError):
                d["reasons"] = []
            out.append(d)
        return out
    finally:
        conn.close()


def transaction_counts():
    """Counts of transactions grouped by decision."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT decision, COUNT(*) AS n FROM transactions GROUP BY decision"
        ).fetchall()
        counts = {"total": 0, "ALLOW": 0, "STEP_UP": 0, "BLOCK": 0}
        for r in rows:
            counts[r["decision"]] = int(r["n"])
            counts["total"] += int(r["n"])
        return counts
    finally:
        conn.close()


def pending_otps(limit=20):
    """Recent, still-usable OTPs joined with their transaction + customer."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT o.id AS otp_id, o.transaction_id, o.used, o.expires_at, "
            "t.amount, t.customer_id, c.name AS customer_name "
            "FROM otps o JOIN transactions t ON t.id = o.transaction_id "
            "LEFT JOIN customers c ON c.id = t.customer_id "
            "WHERE o.used = 0 AND datetime(o.expires_at) >= datetime('now') "
            "ORDER BY o.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_login_events(limit=50):
    """Last N login-type rows stored in transactions (login events land there too)."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM transactions WHERE txn_type = 'login' ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ------------------------------------------------------------------------------ otps

def create_otp(transaction_id, code, expires_at):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO otps (transaction_id, code, expires_at) VALUES (?, ?, ?)",
            (transaction_id, code, expires_at),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_latest_otp(transaction_id):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM otps WHERE transaction_id = ? ORDER BY id DESC LIMIT 1",
            (transaction_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def mark_otp_used(otp_id):
    conn = get_db()
    try:
        conn.execute("UPDATE otps SET used = 1 WHERE id = ?", (otp_id,))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------- alerts

def create_alert(customer_id, severity, message, transaction_id=None, sim_event_id=None,
                 channels=None):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO alerts (customer_id, transaction_id, sim_event_id, severity, message, "
            "channels) VALUES (?, ?, ?, ?, ?, ?)",
            (customer_id, transaction_id, sim_event_id, severity, message,
             json.dumps(channels) if channels else None),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_alerts(limit=30):
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT a.*, c.name AS customer_name FROM alerts a "
            "LEFT JOIN customers c ON c.id = a.customer_id "
            "ORDER BY a.notified_at DESC, a.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["channels"] = json.loads(d["channels"]) if d.get("channels") else []
            except (TypeError, ValueError):
                d["channels"] = []
            out.append(d)
        return out
    finally:
        conn.close()


# ---------------------------------------------------------------------------- agents

def upsert_heartbeat(agent_name, heartbeat_at=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO agents (agent_name, last_heartbeat) VALUES (?, ?) "
            "ON CONFLICT(agent_name) DO UPDATE SET last_heartbeat = excluded.last_heartbeat",
            (agent_name, heartbeat_at or _utcnow()),
        )
        conn.commit()
    finally:
        conn.close()


def list_agents():
    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM agents ORDER BY agent_name").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ----------------------------------------------------------------------- audit logs

def log_audit(event_type, action, entity_id=None, details=None):
    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO audit_logs (event_type, entity_id, action, details_json) VALUES (?, ?, ?, ?)",
            (event_type, entity_id, action, json.dumps(details) if details else None),
        )
        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------------------- helpers

def _utcnow():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")