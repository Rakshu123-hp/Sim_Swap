# memory.md — Project Memory

Keep this file updated. It's the single source of truth for "why did we decide this," so any
teammate (or an AI coding assistant) can pick up the project cold. Every merged PR that
changes a decision should add a line here.

## What this project is

SIM Swap & Transaction Fraud Risk Analytics — a hybrid rules+ML fraud-scoring prototype for
banks. Full context: see `PRD.md`. Full architecture: see `ARCHITECTURE.md`.

## Fixed decisions (do not re-litigate without a team discussion)

- **Backend:** Python + Flask (not Django/Node) — matches report's REST API layer.
- **Database (Phase 1):** SQLite, accessed only through `backend/db/`. MySQL is a Phase 2
  migration target, not Phase 1.
- **Auth:** JWT, issued at login, required on all `/api/risk/*` and `/api/dashboard/*` routes.
- **ML model:** Logistic Regression only for Phase 1 (interpretable, fast to retrain). No
  neural nets / ensembles until Phase 2.
- **Decision labels:** exactly three — `ALLOW`, `STEP_UP`, `BLOCK`. Don't add a fourth
  without updating PRD.md §8 and every module that switches on this value.
- **No production telecom/bank data** — synthetic traffic only, ever, in Phase 1.
- **Frontend:** plain HTML/CSS/JS (single file + module) — decided instead of React to keep
  zero-build, zero-npm Phase 1 demo.

## Module ownership (see TEAM_ROLES.md for full detail)

- `backend/api/` — Member A
- `backend/risk_engine/` — Member B
- `frontend/` — Member C
- `backend/db/`, `simulators/`, `notifications/` — Member D

## API contract snapshot

(Update this whenever an endpoint's request/response shape changes — this is the fastest way
for teammates to avoid breaking each other.)

| Endpoint | Owner | Status | Request | Response |
| --- | --- | --- | --- | --- |
| `POST /api/auth/register` | A | done | `{username, password, role?, name?, email?}` | `{token, user}` |
| `POST /api/auth/login` | A | done | `{username_or_email, password}` (email accepted in `username` key) | `{token, user}` |
| `POST /api/risk/evaluate` | A (calls B's scoring) | done | `{customer_id, event_type, event}` | `{event_id, event_type, decision, risk_score, rule_score, ml_probability, reasons, otp_required}` |
| `POST /api/otp/verify` | A | done | `{transaction_id, code}` | `{valid, message, transaction_id}` |
| `GET /api/dashboard/summary` | A serves, C consumes | done | — | `{stats, transactions[], sim_events[], alerts[], agents[], otps[]}` |
| `POST /api/agents/heartbeat` | D | done | `{agent_name}` | `{status: "ok"}` |

## Open questions / parking lot

- ~~Exact rule weights and score thresholds~~ — pinned: see `backend/risk_engine/config.py`
  (rule weights in §Decision Log below).
- Which geolocation source to use for "location mismatch" signal (see TECH_STACK.md) —
  Phase 1 uses city provided in the event vs customer `home_city`; no external lookup.
- OTP delivery is simulated in logs only (console/log), unless sandbox SMS keys are set.

## Environment / secrets

Never commit real API keys. All keys and secrets live in `.env` (git-ignored); `.env.example`
in the repo root lists every required variable with a placeholder. See TECH_STACK.md §API Keys.

## Decision log (decisions made during the build not pinned in the original docs)

| Date | Decision | By |
| --- | --- | --- |
| build | **Rule weights:** freq +35, time-since-swap +25, new device +20, location mismatch +15, failed logins +10 each (cap 20), amount +45 when `amount > high_amount_threshold`. Final score = 50% rule (0–100) + 50% ML probability×100. `ALLOW < 25`, `BLOCK >= 70`. | build |
| build | `POST /api/auth/register` accepted roles `analyst`/`customer`/`admin`; default `analyst`. | build |
| build | Events can be `login`, `transaction`, or `sim_change`. Each persists to an appropriate table; scoring rules apply across types (amount rule only fires for transactions). | build |
| build | OTPs are 6-digit numeric, 5-minute TTL, plaintext in DB (prototype only), created automatically on STEP_UP decisions. | build |
| build | BLOCK **and** STEP_UP both raise alerts (severity `high` / `medium`); notification calls via `notifications/notifier.py` no-op to console when Twilio/SMTP env vars are unset. | build |
| build | The LR model (`backend/risk_engine/model.joblib`) is auto-trained on the synthetic generator (`synthetic_data.py`) on first startup if absent (`ensure_model()`). | build |
| build | Flask serves `frontend/` statically at `/` so the whole demo runs from one process. | build |
| build | Auth supports email: `users.email` column added (idempotent `ALTER TABLE` migration in `models.init_db()`); login accepts email **or** username; register validates/store email (lowercased, uniqueness enforced in app); login screen has Sign in / Create account tabs. | build |

## Changelog

| Date | Change | By |
| --- | --- | --- |
| kickoff | Repo scaffolded from PRD/architecture kit | — |
| build | Steps 1–8 complete: scaffold, DB schema+models+seed, pure risk engine (rules/features/ML/config), Flask API with JWT + all endpoints, notifications, traffic simulator + heartbeat agent, plain-JS dashboard + OTP screen, pytest suite + e2e. See ARCHITECTURE.md. | build |
| build | Test suite green: 28 tests (`pytest/ test_api`, `test_rules`, `test_e2e`). | build |
| build | Added GitHub Actions CI (`.github/workflows/ci.yml`): installs `requirements.txt` and runs pytest on push/PR. | build |
| build | Clean-clone behavior verified: `python -m backend.db.seed` creates+seeds SQLite; the LR model auto-trains on first risk evaluation if `model.joblib` is absent. | build |
| build | Email-based auth shipped: register/login by email or username; tests green (31 total). Existing `simswap.db` upgraded in place. | build |