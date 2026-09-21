PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE,
    email         TEXT,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'analyst',
    name          TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS customers (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    phone      TEXT,
    email      TEXT,
    home_city  TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sim_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    new_sim_id  TEXT NOT NULL,
    device_id   TEXT,
    ip_address  TEXT,
    recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
    risk_score  REAL,
    decision    TEXT
);

CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER NOT NULL REFERENCES customers(id),
    amount         REAL,
    currency       TEXT DEFAULT 'INR',
    txn_type       TEXT NOT NULL,
    channel        TEXT,
    device_id      TEXT,
    ip_address     TEXT,
    city           TEXT,
    event_time     TEXT,
    risk_score     REAL,
    rule_score     REAL,
    ml_probability REAL,
    decision       TEXT NOT NULL,
    reasons_json   TEXT,
    success        INTEGER DEFAULT 1,
    otp_verified   INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS otps (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL REFERENCES transactions(id),
    code           TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at     TEXT NOT NULL,
    used           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id    INTEGER REFERENCES customers(id),
    transaction_id INTEGER REFERENCES transactions(id),
    sim_event_id   INTEGER REFERENCES sim_events(id),
    severity       TEXT NOT NULL,
    message        TEXT NOT NULL,
    channels       TEXT,
    notified_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name     TEXT NOT NULL UNIQUE,
    last_heartbeat TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type   TEXT NOT NULL,
    entity_id    INTEGER,
    action       TEXT NOT NULL,
    details_json TEXT,
    created_at   TEXT NOT NULL DEFAULT (datetime('now'))
);