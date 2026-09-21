"""Hybrid decision assembly: merge the rule score with the ML probability.

Kept deliberately pure — no Flask, no SQL. The API layer builds the enriched
event dict (adding DB context like sim-change counts / failed-login counts),
calls evaluate_event(), and persists the result.
"""

from backend.risk_engine import config, ml_model, rules


def evaluate_event(event):
    """Enriched event dict in -> full scoring result out.

    Returns: {risk_score, rule_score, ml_probability, decision, reasons}
    """
    rule = rules.evaluate_rules(event)
    probability = ml_model.predict_probability(event)

    final = (config.WEIGHT_RULES * rule["score"]
             + config.WEIGHT_ML * min(max(probability, 0.0), 1.0) * 100)
    decision = config.decide(final, rule["score"], probability)

    return {
        "risk_score": round(final, 2),
        "rule_score": rule["score"],
        "ml_probability": round(probability, 4),
        "decision": decision,
        "reasons": rule["reasons"],
    }