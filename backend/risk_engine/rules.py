"""Rule-based scoring. Pure functions only — no Flask, no SQL, no I/O.

An *enriched* event dict (built by the API layer from the request body plus
customer/context facts pulled from the database) comes in, a
{"score": int, "reasons": [str]} dict comes out.

Expected event keys
-------------------
customer_id             int
event_type              "transaction" | "login" | "sim_change"
amount                  float (transactions only; ignored otherwise)
city                    str                    event-side city
home_city               str                    customer home city
device_id               str
is_new_device           bool
failed_logins           int                    count in window
sim_changes_recent      int                    count in window
hours_since_sim_change  float | None
"""

from backend.risk_engine import config


def _norm(value):
    return (value or "").strip().lower()


def _location_mismatch(city, home_city):
    if not city or not home_city:
        return False
    return _norm(city) != _norm(home_city)


def evaluate_rules(event):
    """Pure rule evaluation. Returns {"score": int (0-100), "reasons": [str]}."""
    score = 0
    reasons = []

    sim_changes = int(event.get("sim_changes_recent") or 0)
    if sim_changes >= config.SIM_CHANGE_FREQ_THRESHOLD:
        score += config.SIM_CHANGE_FREQ_PENALTY
        reasons.append(config.SIM_CHANGE_FREQ_REASON.format(
            n=sim_changes, hours=config.SIM_CHANGE_FREQ_WINDOW_HOURS))

    hours_since = event.get("hours_since_sim_change")
    if hours_since is not None \
            and hours_since <= config.TIME_SINCE_SIM_CHANGE_WINDOW_HOURS:
        score += config.TIME_SINCE_SIM_CHANGE_PENALTY
        reasons.append(config.TIME_SINCE_SIM_CHANGE_REASON.format(
            hours=hours_since, window=config.TIME_SINCE_SIM_CHANGE_WINDOW_HOURS))

    if event.get("is_new_device"):
        score += config.NEW_DEVICE_PENALTY
        reasons.append(config.NEW_DEVICE_REASON.format(device=event.get("device_id")))

    if _location_mismatch(event.get("city"), event.get("home_city")):
        score += config.LOCATION_MISMATCH_PENALTY
        reasons.append(config.LOCATION_MISMATCH_REASON.format(
            city=event.get("city"), home=event.get("home_city")))

    failed = int(event.get("failed_logins") or 0)
    if failed > 0:
        penalty = min(failed * config.FAILED_LOGIN_PENALTY, config.FAILED_LOGIN_CAP)
        score += penalty
        reasons.append(config.FAILED_LOGIN_REASON.format(
            n=failed, hours=config.FAILED_LOGIN_WINDOW_HOURS))

    if event.get("event_type") == "transaction" and event.get("amount") is not None:
        try:
            amount = float(event["amount"])
        except (TypeError, ValueError):
            amount = 0.0
        if amount > config.AMOUNT_HIGH_THRESHOLD:
            score += config.AMOUNT_PENALTY
            reasons.append(config.AMOUNT_REASON.format(
                amount=amount, threshold=config.AMOUNT_HIGH_THRESHOLD))

    score = min(score, config.MAX_RULE_SCORE)
    return {"score": score, "reasons": reasons}