"""Synthetic labeled-data generator for the logistic regression model.

Produces feature rows using the SAME event->feature transform the API uses at
runtime (features.event_to_features), so the model always trains on the exact
feature distribution it will be asked to score live. Deterministic given a seed.
"""

import random

import numpy as np

from backend.risk_engine.features import event_to_features


def _event_for(fraud, rng):
    """Return an enriched event dict whose signals are biased toward fraud/legit."""
    event_type = rng.choice(["transaction", "transaction", "login", "sim_change"])

    if event_type == "sim_change":
        amount = None
    elif event_type == "login":
        amount = None
    else:
        amount = rng.uniform(2000, 2_000_000) if fraud else rng.uniform(1000, 80_000)

    sim_changes = rng.choice([2, 3, 4]) if fraud else rng.choice([0, 1])
    hours_since = rng.uniform(0, 72) if (fraud or sim_changes > 0) \
        else (None if rng.random() < 0.6 else rng.uniform(72, 500))
    is_new_device = rng.random() < (0.75 if fraud else 0.12)
    location_mismatch = rng.random() < (0.7 if fraud else 0.08)
    failed_logins = rng.randint(2, 6) if fraud else rng.randint(0, 1)
    city = "Bengaluru" if location_mismatch else "Haveri"
    home_city = "Haveri"

    return {
        "customer_id": rng.randint(1, 20),
        "event_type": event_type,
        "amount": amount,
        "city": city,
        "home_city": home_city,
        "device_id": "dev-synth",
        "is_new_device": is_new_device,
        "failed_logins": failed_logins,
        "sim_changes_recent": sim_changes,
        "hours_since_sim_change": hours_since,
    }


def generate_synthetic_data(n=6000, seed=42, noise=0.08):
    rng = random.Random(seed)
    X = []
    y = []
    for _ in range(n):
        fraud = rng.random() < 0.25
        event = _event_for(fraud, rng)
        # flip ~8% of labels so the model can't memorize perfectly
        label = int(fraud)
        if rng.random() < noise:
            label = 1 - label
        X.append(event_to_features(event))
        y.append(label)
    return np.asarray(X, dtype=float), np.asarray(y, dtype=int)