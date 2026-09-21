# SIM Swap & Transaction Fraud Risk Analytics

A hybrid rules + machine-learning fraud-scoring prototype for banks. It ingests SIM-change,
login, and transaction events, scores them, returns **ALLOW** / **STEP_UP** / **BLOCK** with
human-readable reasons, persists everything to SQLite, raises alerts, and shows it all on an
analyst dashboard using **synthetic traffic only**.

Read the docs in this order:

1. `PRD.md` — what you're building and why.
2. `ARCHITECTURE.md` — how it fits together and the exact repo layout.
3. `TECH_STACK.md` — locked stack choices + API keys.
4. `TEAM_ROLES.md` — module ownership.
5. `memory.md` — living decision log; it has a changelog at the bottom.

## Quickstart

```bash
git init && copy .env.example .env        # (Windows) or: cp .env.example .env
pip install -r requirements.txt
# first run trains + persists the logistic-regression model automatically
python -m backend.api.app                # starts Flask on :5000 (with reload)
python -m backend.risk_engine.train_model   # optional: retrain model manually
```

Separate processes (see `simulators/` and `notifications/`):

```bash
python -m simulators.traffic_gen --rate 2 --duration 60   # synthetic event stream
python -m simulators.heartbeat_agent --interval 10        # agent heartbeat
```

If Twilio/SMTP env vars are unset, notifications **log to console** instead of sending, so
the whole system runs with zero external keys.

## Run the tests

```bash
python -m pytest tests -v
```

## End-to-end demo script

`tests/test_e2e.py` registers a user, submits a high-risk transaction, confirms it is
**BLOCKed**, and asserts an alert row exists. Open the dashboard at
`http://localhost:5000` (static frontend is served by Flask) or use `frontend/index.html`
directly.