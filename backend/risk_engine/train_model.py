"""Train + persist the logistic regression model on synthetic data.

Run from the repo root:  python -m backend.risk_engine.train_model
"""

import joblib

from backend.risk_engine import config, ml_model
from backend.risk_engine.features import FEATURE_NAMES
from backend.risk_engine.synthetic_data import generate_synthetic_data


def train_and_save(verbose=True):
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    X_train, y_train = generate_synthetic_data(config.SYNTHETIC_TRAIN_SAMPLES,
                                               seed=config.ML_MODEL_SEED)
    X_test, y_test = generate_synthetic_data(config.SYNTHETIC_TEST_SAMPLES,
                                             seed=config.ML_MODEL_SEED + 1)

    scaler = StandardScaler().fit(X_train)
    clf = LogisticRegression(max_iter=2000, random_state=config.ML_MODEL_SEED)
    clf.fit(scaler.transform(X_train), y_train)

    accuracy = float(clf.score(scaler.transform(X_test), y_test))
    joblib.dump(
        {"model": clf, "scaler": scaler, "features": FEATURE_NAMES},
        ml_model.model_path(),
    )
    if verbose:
        print(f"Trained logistic regression on {len(X_train)} synthetic rows.")
        print(f"Saved -> {ml_model.model_path()}")
        print(f"Hold-out accuracy: {accuracy:.3f}")
    return accuracy


if __name__ == "__main__":
    train_and_save()