"""Logistic regression model: load / lazy-train / predict fraud probability.

Pure module (numpy + sklearn + joblib). If no persisted model exists yet, it
trains one on the synthetic generator so the API works out of the box.
"""

import os
from pathlib import Path

import joblib
import numpy as np

from backend.risk_engine import config


def model_path():
    p = Path(config.MODEL_SAVE_PATH)
    if p.is_absolute():
        return str(p)
    return str(Path(__file__).resolve().parents[2] / p)


def load_model():
    path = model_path()
    if os.path.exists(path):
        return joblib.load(path)
    return None


def ensure_model():
    """Return a trained package {"model", "scaler", "features"}, training if absent."""
    package = load_model()
    if package is None:
        from backend.risk_engine import train_model
        train_model.train_and_save()
        package = load_model()
    return package


def predict_probability(x):
    """Fraud probability (0-1) for an enriched event dict or a feature row."""
    if isinstance(x, dict):
        from backend.risk_engine.features import event_to_features
        vector = np.asarray([event_to_features(x)], dtype=float)
    else:
        vector = np.asarray(x, dtype=float).reshape(1, -1)

    package = ensure_model()
    scaler = package["scaler"]
    clf = package["model"]
    proba = clf.predict_proba(scaler.transform(vector))[0]
    return float(proba[1])