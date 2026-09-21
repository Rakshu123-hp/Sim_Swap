"""Thresholds and weights for the hybrid risk engine.

Everything the rule engine, the ML merge, and the decision assembly needs
lives here so it can be tuned in one place. Every rule/reason string is
defined here too.
"""

# ------------------------------------------------------------- decision thresholds
# Hybrid score: 0-100. Below ALLOW_THRESHOLD -> ALLOW, at/above BLOCK_THRESHOLD -> BLOCK,
# in between -> STEP_UP. Thresholds are inclusive at the top end.
ALLOW_THRESHOLD = 25
BLOCK_THRESHOLD = 70

# How the two signals are merged into one 0-100 risk score.
WEIGHT_RULES = 0.5
WEIGHT_ML = 0.5
MAX_RULE_SCORE = 100

# Safety nets: a pure rule score at/above BLOCK, or an ML probability at/above
# ML_BLOCK_PROBABILITY, is BLOCKed no matter what the merged score says.
ML_BLOCK_PROBABILITY = 0.92

# ------------------------------------------------------------------- rule tuning
# 1. SIM-change frequency: too many SIM swaps in a short window.
SIM_CHANGE_FREQ_WINDOW_HOURS = 24
SIM_CHANGE_FREQ_THRESHOLD = 2
SIM_CHANGE_FREQ_PENALTY = 35
SIM_CHANGE_FREQ_REASON = "Multiple SIM changes ({n}) for this customer in the last {hours}h"

# 2. Time since the most recent SIM change.
TIME_SINCE_SIM_CHANGE_WINDOW_HOURS = 72
TIME_SINCE_SIM_CHANGE_PENALTY = 25
TIME_SINCE_SIM_CHANGE_REASON = (
    "Event occurred {hours:.0f}h after a SIM change (window {window}h)"
)

# 3. New device for this customer.
NEW_DEVICE_PENALTY = 20
NEW_DEVICE_REASON = "Device '{device}' has never been seen for this customer"

# 4. Location mismatch vs the customer's home city.
LOCATION_MISMATCH_PENALTY = 15
LOCATION_MISMATCH_REASON = (
    "Event city '{city}' does not match the customer's home city '{home}'"
)

# 5. Failed-login count in the window (per-login, capped).
FAILED_LOGIN_WINDOW_HOURS = 24
FAILED_LOGIN_PENALTY = 10
FAILED_LOGIN_CAP = 20
FAILED_LOGIN_REASON = "{n} failed login attempt(s) in the last {hours}h"

# 6. Transaction amount.
AMOUNT_HIGH_THRESHOLD = 100000.0
AMOUNT_PENALTY = 45
AMOUNT_REASON = "Transaction amount {amount} exceeds the high-risk threshold of {threshold}"

# ------------------------------------------------------------------------- models
ML_MODEL_SEED = 42
MODEL_SAVE_PATH = "backend/risk_engine/model.joblib"
SYNTHETIC_TRAIN_SAMPLES = 6000
SYNTHETIC_TEST_SAMPLES = 2000


def decide(final_score, rule_score, ml_probability):
    """Map a hybrid score to one of ALLOW / STEP_UP / BLOCK.

    rule_score and ml_probability safety nets are applied before the merged
    score so a clearly fraudulent signal can never be downgraded by the other
    half of the hybrid.
    """
    if rule_score >= BLOCK_THRESHOLD:
        return "BLOCK"
    if ml_probability >= ML_BLOCK_PROBABILITY:
        return "BLOCK"
    if final_score < ALLOW_THRESHOLD:
        return "ALLOW"
    if final_score >= BLOCK_THRESHOLD:
        return "BLOCK"
    return "STEP_UP"