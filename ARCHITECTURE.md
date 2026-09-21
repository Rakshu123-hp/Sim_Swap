# Architecture — SIM Swap & Transaction Fraud Risk Analytics

> Note: the original ARCHITECTURE.md was not included in the project kit; this file
> reconstructs it from every reference made to it across PRD.md, TECH_STACK.md,
> TEAM_ROLES.md, README.md, and BUILD_PROMPT.md so the exact layout and schema the
> team agreed on are pinned in one place.

## 1. System overview

A hybrid **rules + logistic-regression** risk scoring engine wrapped in a Flask REST API.
Synthetic clients (the traffic simulator and demo agents) post login / transaction / SIM-change
events. Every event is scored to one of **ALLOW / STEP_UP / BLOCK** with human-readable
reasons, persisted to SQLite, and — for high-risk or medium-risk outcomes — raises an alert
(SMS/email if sandbox keys are configured, console-log otherwise). A dashboard polls the API
and renders transactions, SIM events, alerts, risk scores, and agent heartbeats.

```
                    ┌────────────────────────────────────────────┐
                    │                 Frontend (plain JS)        │
                    │   Analyst dashboard  ·  OTP step-up screen │
                    └───────────────▲────────────────────────────┘
                                    │ GET /api/dashboard/summary
                                    │ POST /api/otp/verify
                    ┌───────────────┴────────────────────────────┐
                    │              backend/api (Flask)           │
                    │  JWT auth · validation · orchestration     │
                    └───────▲───────────────┬────────────────────┘
          synthetic events │               │ scoring call
                    ┌───────┴─────┐   ┌─────┴─────────────────────┐
                    │ simulators/ │   │    backend/risk_engine    │
                    │ traffic_gen │   │ rules.py → features.py →  │
                    │ heartbeat   │   │ ml_model.py → config.py   │
                    └─────────────┘   └───────────┬───────────────┘
                                                  │ persist
                    ┌──────────────────────────────┴──────────────┐
                    │              backend/db (SQLite)           │
                    │  users · customers · sim_events ·          │
                    │  transactions · otps · alerts · agents     │
                    └──────────────────────────┬─────────────────┘
                                               │ raise alert
                    ┌──────────────────────────▼─────────────────┐
                    │          notifications/ (Twilio / SMTP)    │
                    │  logs to console when keys are unset       │
                    └────────────────────────────────────────────┘
```

## 2. Layering rules

- `risk_engine` is **pure** — zero Flask, zero SQL imports. The API layer calls it, never the
  other way around.
- `backend/db` is the only module that touches SQLite. `models.py` exposes thin data-access
  functions (no business logic).
- `notifications`, `simulators`, and the frontend only ever talk to the API over HTTP.
- Folders never mix concerns: `api`, `risk_engine`, `db`, `frontend`, `simulators`,
  `notifications`, `tests` stay in their own folders per §3.

## 3. Repo layout

```
simswap-fraud-analytics/
├── README.md                 # read-me-first overview + quickstart
├── PRD.md                    # product spec
├── ARCHITECTURE.md           # this file
├── TECH_STACK.md             # locked stack + API keys
├── TEAM_ROLES.md             # module ownership per member
├── memory.md                 # living decision log + API contract table
├── BUILD_PROMPT.md           # the build prompt that generated this repo
├── requirements.txt
├── .env.example              # commit this; never commit .env
├── backend/
│   ├── api/                  # [Member A] Flask app, routes, JWT
│   ├── risk_engine/          # [Member B] rules, features, ML, config (pure)
│   └── db/                   # [Member D] schema.sql, models.py, seed.py
├── frontend/                 # [Member C] plain HTML/CSS/JS dashboard + OTP screen
├── simulators/               # [Member D] traffic generator + agent heartbeat
├── notifications/            # [Member D] SMS/email notifier (safe no-op w/o keys)
└── tests/                    # [Member D] pytest: unit + API + end-to-end
```

## 4. Database schema (SQLite)

Tables (see `backend/db/schema.sql` for exact DDL):

| Table | Purpose | Key columns |
| --- | --- | --- |
| `users` | App logins (analyst / customer / admin) | `id`, `username` UNIQUE, `password_hash`, `role` |
| `customers` | Demo bank customers | `id`, `name`, `phone`, `email`, `home_city` |
| `sim_events` | SIM-card change events | `id`, `customer_id`, `new_sim_id`, `device_id`, `ip_address`, `recorded_at` |
| `transactions` | Transaction/login events + decision | `id`, `customer_id`, `amount`, `txn_type`, `channel`, `device_id`, `ip_address`, `city`, `risk_score`, `decision`, `reasons_json`, `ml_probability`, `created_at` |
| `otps` | Step-up codes | `id`, `transaction_id`, `code`, `created_at`, `expires_at`, `used` |
| `alerts` | Persisted alert records | `id`, `customer_id`, `transaction_id`, `sim_event_id`, `severity`, `message`, `notified_at` |
| `agents` | Demo/monitoring agent heartbeats | `id`, `agent_name` UNIQUE, `last_heartbeat` |
| `audit_logs` | Every risk evaluation trace | `id`, `event_type`, `entity_id`, `action`, `details_json`, `created_at` |

Foreign keys enforce `customers`/`transactions`/`sim_events`/`alerts` relationships. SQLite
file lives at `backend/db/simswap.db` (path from `DATABASE_URL` env var).

## 5. Hybrid decision flow

1. `rules.py` — pure function: event dict in → `{score: int, reasons: [str]}` out. Rules:
   SIM-change frequency, time-since-SIM-change, new device, location mismatch,
   failed-login count, transaction amount.
2. `features.py` — turns the event into the ML feature vector.
3. `ml_model.py` — loads trained logistic regression; returns fraud probability (0–1).
4. `config.py` — thresholds and weights:
   - `final_score = WEIGHT_RULES * rule_score + WEIGHT_ML * (ml_probability * 100)`
   - `< ALLOW_THRESHOLD` → **ALLOW** · `>= BLOCK_THRESHOLD` → **BLOCK** · else **STEP_UP**
5. `backend/api` persists the outcome via `backend/db/models.py`, creates an OTP on
   STEP_UP, raises an alert on BLOCK (and STEP_UP), and can fire notification callbacks.

## 6. API contract (finalized shapes)

| Method & path | Auth | Request | Response |
| --- | --- | --- | --- |
| `POST /api/auth/register` | public | `{username, password, role?, name?}` | `{token, user}` |
| `POST /api/auth/login` | public | `{username, password}` | `{token, user}` |
| `POST /api/risk/evaluate` | JWT | `{customer_id, event_type, event}` | `{event_id, event_type, decision, risk_score, rule_score, ml_probability, reasons, otp_required}` |
| `POST /api/otp/verify` | JWT | `{transaction_id, code}` | `{valid, message, transaction_id}` |
| `GET /api/dashboard/summary` | JWT | — | `{stats, transactions[], sim_events[], alerts[], agents[], otps[]}` |
| `POST /api/agents/heartbeat` | public | `{agent_name}` | `{status: "ok"}` |

Validation failures return 4xx with a `{error: {field: message}}` body. Unknown customers /
bad event types return 404/400 respectively.