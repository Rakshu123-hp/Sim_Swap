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
        _ensure_column(conn, "users", "updated_at", "ALTER TABLE users ADD COLUMN updated_at TEXT")
        _ensure_column(conn, "customers", "user_id",
                       "ALTER TABLE customers ADD COLUMN user_id INTEGER REFERENCES users(id)")
        _ensure_column(conn, "customers", "status",
                       "ALTER TABLE customers ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        _ensure_column(conn, "alerts", "status",
                       "ALTER TABLE alerts ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
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


def touch_user(user_id):
    """Stamp a user's updated_at (login/register)."""
    conn = get_db()
    try:
        conn.execute("UPDATE users SET updated_at = datetime('now') WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ----------------------------------------------------------------------- customers

def create_customer(name, phone=None, email=None, home_city=None, user_id=None, status="active"):
    conn = get_db()
    try:
        cur = conn.execute(
            "INSERT INTO customers (name, phone, email, home_city, user_id, status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (name, phone, email, home_city, user_id, status),
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


def get_customer_by_user(user_id):
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM customers WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_customer_by_email(email):
    if not email:
        return None
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM customers WHERE email = ? LIMIT 1", (email,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_or_create_customer_for_user(user):
    """Find the customer linked to a user; create one if missing.

    Registration and risk evaluation both guarantee every user has a customer,
    so a legacy user (created before the link existed) is repaired in place.
    """
    existing = get_customer_by_user(user["id"])
    if existing:
        return existing
    customer_id = create_customer(
        user_id=user["id"],
        name=user.get("name") or user["username"],
        email=user.get("email"),
        home_city="Haveri",
    )
    return get_customer(customer_id)


def list_customers():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT c.*, u.username AS owner_username, u.role AS owner_role "
            "FROM customers c LEFT JOIN users u ON u.id = c.user_id ORDER BY c.id"
        ).fetchall()
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


def list_sim_events(limit=25, customer_id=None):
    conn = get_db()
    try:
        sql = ("SELECT s.*, c.name AS customer_name FROM sim_events s "
               "LEFT JOIN customers c ON c.id = s.customer_id")
        params = []
        if customer_id is not None:
            sql += " WHERE s.customer_id = ?"
            params.append(customer_id)
        sql += " ORDER BY s.recorded_at DESC, s.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
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


def list_transactions(limit=25, customer_id=None):
    conn = get_db()
    try:
        sql = ("SELECT t.*, c.name AS customer_name FROM transactions t "
               "LEFT JOIN customers c ON c.id = t.customer_id")
        params = []
        if customer_id is not None:
            sql += " WHERE t.customer_id = ?"
            params.append(customer_id)
        sql += " ORDER BY t.created_at DESC, t.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
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


def transaction_counts(customer_id=None):
    """Counts of transaction rows grouped by decision (optionally per customer)."""
    conn = get_db()
    try:
        sql = "SELECT decision, COUNT(*) AS n FROM transactions"
        params = []
        if customer_id is not None:
            sql += " WHERE customer_id = ?"
            params.append(customer_id)
        sql += " GROUP BY decision"
        rows = conn.execute(sql, params).fetchall()
        counts = {"total": 0, "ALLOW": 0, "STEP_UP": 0, "BLOCK": 0}
        for r in rows:
            counts[r["decision"]] = int(r["n"])
            counts["total"] += int(r["n"])
        return counts
    finally:
        conn.close()


def customer_stats(customer_id):
    """Full stats block for one customer's dashboard."""
    conn = get_db()
    try:
        txn_rows = conn.execute(
            "SELECT decision, COUNT(*) AS n FROM transactions "
            "WHERE customer_id = ? AND txn_type != 'login' GROUP BY decision",
            (customer_id,),
        ).fetchall()
        txn_counts = {"total": 0, "ALLOW": 0, "STEP_UP": 0, "BLOCK": 0}
        for r in txn_rows:
            txn_counts[r["decision"]] = int(r["n"])
            txn_counts["total"] += int(r["n"])

        login_row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(success), 0) AS ok "
            "FROM transactions WHERE customer_id = ? AND txn_type = 'login'",
            (customer_id,),
        ).fetchone()
        sim_count = conn.execute(
            "SELECT COUNT(*) AS n FROM sim_events WHERE customer_id = ?", (customer_id,)
        ).fetchone()
        alert_count = conn.execute(
            "SELECT COUNT(*) AS n FROM alerts WHERE customer_id = ?", (customer_id,)
        ).fetchone()

        return {
            **txn_counts,
            "login_attempts": int(login_row["n"]),
            "login_success": int(login_row["ok"]),
            "login_failed": int(login_row["n"]) - int(login_row["ok"]),
            "sim_changes": int(sim_count["n"]),
            "alerts": int(alert_count["n"]),
        }
    finally:
        conn.close()


def pending_otps(limit=20, customer_id=None):
    """Recent, still-usable OTPs joined with their transaction + customer."""
    conn = get_db()
    try:
        sql = ("SELECT o.id AS otp_id, o.transaction_id, o.used, o.expires_at, "
               "t.amount, t.customer_id, c.name AS customer_name "
               "FROM otps o JOIN transactions t ON t.id = o.transaction_id "
               "LEFT JOIN customers c ON c.id = t.customer_id "
               "WHERE o.used = 0 AND datetime(o.expires_at) >= datetime('now')")
        params = []
        if customer_id is not None:
            sql += " AND t.customer_id = ?"
            params.append(customer_id)
        sql += " ORDER BY o.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def list_login_events(limit=50, customer_id=None):
    """Last N login-type rows stored in transactions (login events land there too)."""
    conn = get_db()
    try:
        sql = ("SELECT t.*, c.name AS customer_name FROM transactions t "
               "LEFT JOIN customers c ON c.id = t.customer_id WHERE t.txn_type = 'login'")
        params = []
        if customer_id is not None:
            sql += " AND t.customer_id = ?"
            params.append(customer_id)
        sql += " ORDER BY t.created_at DESC, t.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
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


def list_alerts(limit=30, customer_id=None, status=None):
    conn = get_db()
    try:
        sql = ("SELECT a.*, c.name AS customer_name FROM alerts a "
               "LEFT JOIN customers c ON c.id = a.customer_id")
        params = []
        where = []
        if customer_id is not None:
            where.append("a.customer_id = ?")
            params.append(customer_id)
        if status is not None:
            where.append("a.status = ?")
            params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY a.notified_at DESC, a.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
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


def risk_summary(customer_id, limit=50):
    """Per-customer risk history: scores/decisions from transactions + SIM events."""
    conn = get_db()
    try:
        txns = conn.execute(
            "SELECT 'transaction' AS event_type, id AS event_id, risk_score, decision, "
            "created_at AS recorded_at FROM transactions WHERE customer_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
        sims = conn.execute(
            "SELECT 'sim_change' AS event_type, id AS event_id, risk_score, decision, "
            "recorded_at FROM sim_events WHERE customer_id = ? "
            "ORDER BY recorded_at DESC, id DESC LIMIT ?",
            (customer_id, limit),
        ).fetchall()
        events = [dict(r) for r in txns] + [dict(r) for r in sims]

        scores = [e["risk_score"] for e in events if e.get("risk_score") is not None]
        distribution = {"low": 0, "medium": 0, "high": 0}
        for s in scores:
            if s < 25:
                distribution["low"] += 1
            elif s < 70:
                distribution["medium"] += 1
            else:
                distribution["high"] += 1

        return {
            "total_events": len(events),
            "avg_risk_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "max_risk_score": round(max(scores), 2) if scores else 0,
            "distribution": distribution,
            "events": events,
        }
    finally:
        conn.close()


# -------------------------------------------------------------------------- admin

def count_users():
    conn = get_db()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])
    finally:
        conn.close()


def count_customers():
    conn = get_db()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()["n"])
    finally:
        conn.close()


def list_users():
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT u.id, u.username, u.email, u.role, u.name, u.created_at, u.updated_at, "
            "c.id AS customer_id FROM users u LEFT JOIN customers c ON c.user_id = u.id "
            "ORDER BY u.id"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def analytics():
    """System-wide aggregates for analyst/admin dashboards."""
    conn = get_db()
    try:
        counts = transaction_counts()
        active_alerts = int(conn.execute(
            "SELECT COUNT(*) AS n FROM alerts WHERE status = 'open'").fetchone()["n"])
        blocked = int(counts.get("BLOCK", 0))

        risk_dist = {"low": 0, "medium": 0, "high": 0}
        for table in ("transactions", "sim_events"):
            rows = conn.execute(
                "SELECT risk_score FROM %s WHERE risk_score IS NOT NULL" % table).fetchall()
            for r in rows:
                s = r["risk_score"]
                if s < 25:
                    risk_dist["low"] += 1
                elif s < 70:
                    risk_dist["medium"] += 1
                else:
                    risk_dist["high"] += 1

        by_city = [dict(r) for r in conn.execute(
            "SELECT COALESCE(city, 'unknown') AS city, COUNT(*) AS n FROM transactions "
            "GROUP BY city ORDER BY n DESC LIMIT 15").fetchall()]
        by_channel = [dict(r) for r in conn.execute(
            "SELECT COALESCE(channel, 'unknown') AS channel, COUNT(*) AS n FROM transactions "
            "GROUP BY channel ORDER BY n DESC LIMIT 15").fetchall()]
        over_time = [dict(r) for r in conn.execute(
            "SELECT date(created_at) AS day, COUNT(*) AS n FROM transactions "
            "GROUP BY day ORDER BY day DESC LIMIT 30").fetchall()]
        high_risk_customers = [dict(r) for r in conn.execute(
            "SELECT t.customer_id, c.name AS customer_name, COUNT(*) AS blocked "
            "FROM transactions t LEFT JOIN customers c ON c.id = t.customer_id "
            "WHERE t.decision = 'BLOCK' GROUP BY t.customer_id "
            "ORDER BY blocked DESC, t.customer_id LIMIT 10").fetchall()]

        return {
            "total_transactions": int(counts["total"]),
            "allowed": int(counts["ALLOW"]),
            "step_up": int(counts["STEP_UP"]),
            "blocked": blocked,
            "high_risk_transactions": blocked,
            "active_alerts": active_alerts,
            "risk_distribution": risk_dist,
            "transactions_by_city": by_city,
            "transactions_by_channel": by_channel,
            "transactions_over_time": over_time,
            "high_risk_customers": high_risk_customers,
        }
    finally:
        conn.close()


# ------------------------------------------------------------- demo-traffic lease

DEMO_TRAFFIC_LEASE_SECONDS = 30
_DEMO_AGENT_KEY = "demo-traffic"


def demo_traffic_claim(agent_key=_DEMO_AGENT_KEY, lease_seconds=DEMO_TRAFFIC_LEASE_SECONDS):
    """Single-generator guard across Gunicorn workers.

    INSERT a unique agents row. If another process already owns it, steal the
    lease only after it has gone stale. Returns True when this process is the
    (new) owner.
    """
    conn = get_db()
    now = _utcnow()
    try:
        conn.execute(
            "INSERT INTO agents (agent_name, last_heartbeat) VALUES (?, ?)",
            (agent_key, now),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        try:
            cur = conn.execute(
                "UPDATE agents SET last_heartbeat = ? WHERE agent_name = ? "
                "AND datetime(last_heartbeat) < datetime('now', ?)",
                (now, agent_key, "-%d seconds" % lease_seconds),
            )
            conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error:
            return False
    finally:
        conn.close()


def demo_traffic_renew(agent_key=_DEMO_AGENT_KEY):
    """Extend the lease. True when this process still owns the row."""
    conn = get_db()
    try:
        cur = conn.execute(
            "UPDATE agents SET last_heartbeat = ? WHERE agent_name = ?",
            (_utcnow(), agent_key),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.Error:
        return False
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