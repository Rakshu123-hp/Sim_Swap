"""Rule + threshold behavior for the pure risk engine."""

from backend.risk_engine import config, rules
from backend.risk_engine.engine import evaluate_event


def base_event(**overrides):
    event = {
        "customer_id": 1,
        "event_type": "transaction",
        "amount": 1000.0,
        "city": "Haveri",
        "home_city": "Haveri",
        "device_id": "dev-known",
        "is_new_device": False,
        "failed_logins": 0,
        "sim_changes_recent": 0,
        "hours_since_sim_change": None,
    }
    event.update(overrides)
    return event


def test_clean_event_scores_zero():
    result = rules.evaluate_rules(base_event())
    assert result["score"] == 0
    assert result["reasons"] == []


def test_sim_change_frequency_rule_triggers():
    result = rules.evaluate_rules(base_event(sim_changes_recent=config.SIM_CHANGE_FREQ_THRESHOLD))
    assert result["score"] == config.SIM_CHANGE_FREQ_PENALTY
    assert any("SIM changes" in r for r in result["reasons"])


def test_time_since_sim_change_rule():
    inside = rules.evaluate_rules(base_event(hours_since_sim_change=10,
                                             sim_changes_recent=0))
    assert inside["score"] == config.TIME_SINCE_SIM_CHANGE_PENALTY
    outside = rules.evaluate_rules(base_event(hours_since_sim_change=1000,
                                              sim_changes_recent=0))
    assert outside["score"] == 0


def test_new_device_rule():
    result = rules.evaluate_rules(base_event(is_new_device=True, device_id="dev-new"))
    assert result["score"] == config.NEW_DEVICE_PENALTY
    assert any("never been seen" in r for r in result["reasons"])


def test_location_mismatch_rule_is_case_insensitive():
    result = rules.evaluate_rules(base_event(city="BENGALURU", home_city="haveri"))
    assert result["score"] == config.LOCATION_MISMATCH_PENALTY
    same = rules.evaluate_rules(base_event(city="Haveri", home_city="Haveri"))
    assert same["score"] == 0


def test_failed_logins_are_capped():
    result = rules.evaluate_rules(base_event(failed_logins=10))
    assert result["score"] == config.FAILED_LOGIN_CAP


def test_amount_rule_only_applies_to_transactions():
    txn = rules.evaluate_rules(base_event(amount=1_000_000))
    assert txn["score"] == config.AMOUNT_PENALTY
    login = rules.evaluate_rules(base_event(event_type="login", amount=1_000_000))
    assert login["score"] == 0


def test_rule_score_is_capped():
    result = rules.evaluate_rules(base_event(
        sim_changes_recent=5, hours_since_sim_change=1, is_new_device=True,
        city="Delhi", failed_logins=8, amount=5_000_000,
    ))
    assert result["score"] == config.MAX_RULE_SCORE


def test_decide_thresholds():
    assert config.decide(10, 0, 0.05) == "ALLOW"
    assert config.decide(50, 30, 0.3) == "STEP_UP"
    assert config.decide(80, 60, 0.4) == "BLOCK"
    # safety nets
    assert config.decide(0, config.BLOCK_THRESHOLD, 0.0) == "BLOCK"
    assert config.decide(0, 0, config.ML_BLOCK_PROBABILITY) == "BLOCK"


def test_evaluate_event_clean_is_allow():
    result = evaluate_event(base_event())
    assert result["decision"] == "ALLOW"
    assert result["reasons"] == []


def test_evaluate_event_high_risk_is_block():
    result = evaluate_event(base_event(
        sim_changes_recent=3, hours_since_sim_change=2, is_new_device=True,
        city="Delhi", failed_logins=3, amount=2_000_000,
    ))
    assert result["decision"] == "BLOCK"
    assert len(result["reasons"]) >= 1
    assert result["rule_score"] >= config.BLOCK_THRESHOLD