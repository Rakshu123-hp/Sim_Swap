"""Feature engineering: turns an enriched event dict into an ML feature vector.

The feature list is the single source of truth for the model input and MUST stay
in sync with synthetic_data.py / train_model.py. Keep the order fixed.
"""

import math

FEATURE_NAMES = [
    "amount_log",             # log1p(amount); 0 for non-transaction events
    "sim_changes_recent",     # count of SIM changes in window
    "hours_since_sim_change", # 0 when there was no recent SIM change
    "is_new_device",          # 0/1
    "location_mismatch",      # 0/1
    "failed_logins",          # count in window (capped by rules, raw here is fine)
    "is_sim_change_event",    # 0/1 event type is sim_change
    "is_login_event",         # 0/1 event type is login
]


def event_to_features(event):
    """Enriched event dict -> list/array of numbers matching FEATURE_NAMES order.

    Returns a plain list; ml_model converts it to a numpy row.
    """
    event_type = event.get("event_type")

    amount = event.get("amount")
    try:
        amount = float(amount) if amount is not None else 0.0
    except (TypeError, ValueError):
        amount = 0.0
    amount_log = math.log1p(amount) / 12.0  # roughly normalizes lakh-scale amounts

    hours_since = event.get("hours_since_sim_change")
    hours_since_value = float(hours_since) if hours_since is not None else 0.0

    return [
        amount_log,
        float(event.get("sim_changes_recent") or 0),
        hours_since_value,
        1.0 if event.get("is_new_device") else 0.0,
        1.0 if event.get("home_city") and event.get("city")
            and str(event.get("city")).strip().lower()
            != str(event.get("home_city")).strip().lower() else 0.0,
        float(event.get("failed_logins") or 0),
        1.0 if event_type == "sim_change" else 0.0,
        1.0 if event_type == "login" else 0.0,
    ]