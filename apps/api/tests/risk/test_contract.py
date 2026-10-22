"""Contract tests for the published risk engine surface.

The weights, thresholds, level bands and reason codes are part of the risk
contract of this deliverable. They may not drift silently: any change has to
be an explicit decision that shows up in this file.
"""

import inspect

import pytest

from app.core.config import settings
from app.risk.config import get_risk_config
from app.risk.engine import BehavioralTwinEngine
from app.risk.schemas import RiskEvaluationRequest, RiskEvaluationResult
from app.risk.service import DeterministicRiskEngineService, get_risk_engine
from app.schemas.sessions import TrustLevel

EXPECTED_WEIGHTS = {
    "weight_new_device": 18.0,
    "weight_new_location": 14.0,
    "weight_unusual_time": 11.0,
    "weight_new_payee": 16.0,
    "weight_large_payout": 21.0,
    "weight_new_payee_large_payout": 9.0,
    "weight_payee_add_then_payout": 9.0,
    "weight_canary_interaction": 11.0,
}

EXPECTED_THRESHOLDS = {
    "threshold_restricted": 30.0,
    "threshold_decoy": 60.0,
    "threshold_isolated": 90.0,
}


def test_signal_weights_are_frozen():
    config = get_risk_config()
    for name, expected in EXPECTED_WEIGHTS.items():
        assert getattr(config, name) == expected, name


def test_trust_band_thresholds_are_frozen():
    config = get_risk_config()
    for name, expected in EXPECTED_THRESHOLDS.items():
        assert getattr(config, name) == expected, name
    assert config.baseline_score == 0.0
    assert config.provisional_factor == 0.25
    assert config.decay_points_per_event == 5.0


def test_the_engine_service_interface_is_stable():
    signature = inspect.signature(DeterministicRiskEngineService.evaluate)
    assert list(signature.parameters) == ["self", "db", "session", "request"]
    assert isinstance(
        inspect.get_annotations(DeterministicRiskEngineService.evaluate)["return"],
        object,
    )
    assert get_risk_engine() is not None


def test_the_evaluation_result_is_bounded():
    fields = RiskEvaluationResult.model_fields
    score = fields["risk_score"]
    bounds = {type(item).__name__: item for item in score.metadata}
    assert bounds["Ge"].ge == 0.0
    assert bounds["Le"].le == 100.0
    assert fields["reason_codes"].default_factory() == []
    assert fields["risk_signals"].default_factory() == {}


def test_the_request_accepts_the_documented_optional_fields():
    fields = RiskEvaluationRequest.model_fields
    for name in (
        "occurred_at",
        "event_id",
        "device_id",
        "ip_address",
        "event_type",
    ):
        assert name in fields
        assert fields[name].default is None
    assert fields["action_type"].default == "payout"
    assert fields["amount"].default == 0.0
    assert fields["recipient"].default == ""
    assert fields["context"].default_factory() == {}


def test_the_trust_level_bands_match_the_configured_thresholds():
    config = get_risk_config()
    assert TrustLevel.RESTRICTED.value.lower() == "restricted"
    assert config.threshold_restricted < config.threshold_decoy < config.threshold_isolated
    assert TrustLevel.NORMAL.value.lower() == "normal"
    assert TrustLevel.DECOY.value.lower() == "decoy"
    assert TrustLevel.ISOLATED.value.lower() == "isolated"


def test_the_documented_environment_settings_exist():
    for name in (
        "RISK_WEIGHT_NEW_DEVICE",
        "RISK_WEIGHT_NEW_LOCATION",
        "RISK_WEIGHT_UNUSUAL_TIME",
        "RISK_WEIGHT_NEW_PAYEE",
        "RISK_WEIGHT_LARGE_PAYOUT",
        "RISK_WEIGHT_NEW_PAYEE_LARGE_PAYOUT",
        "RISK_WEIGHT_PAYEE_ADD_THEN_PAYOUT",
        "RISK_WEIGHT_CANARY_INTERACTION",
        "RISK_THRESHOLD_RESTRICTED",
        "RISK_THRESHOLD_DECOY",
        "RISK_THRESHOLD_ISOLATED",
        "RISK_MIN_SAMPLES",
        "RISK_LARGE_PAYOUT_THRESHOLD",
        "RISK_LARGE_PAYOUT_RELATIVE_FACTOR",
        "RISK_AMOUNT_BASELINE_MIN_SAMPLES",
        "RISK_HOUR_CONFIRM_OBSERVATIONS",
        "RISK_HOUR_CONCENTRATION_MIN",
        "RISK_CONTEXT_CONFIRM_OBSERVATIONS",
    ):
        assert hasattr(settings, name), name


@pytest.mark.parametrize(
    "name,value",
    [
        ("RISK_WEIGHT_NEW_DEVICE", 18),
        ("RISK_WEIGHT_NEW_LOCATION", 14),
        ("RISK_WEIGHT_UNUSUAL_TIME", 11),
        ("RISK_WEIGHT_NEW_PAYEE", 16),
        ("RISK_WEIGHT_LARGE_PAYOUT", 21),
        ("RISK_WEIGHT_NEW_PAYEE_LARGE_PAYOUT", 9),
        ("RISK_WEIGHT_PAYEE_ADD_THEN_PAYOUT", 9),
        ("RISK_WEIGHT_CANARY_INTERACTION", 11),
        ("RISK_THRESHOLD_RESTRICTED", 30),
        ("RISK_THRESHOLD_DECOY", 60),
        ("RISK_THRESHOLD_ISOLATED", 90),
        ("RISK_HOUR_CONCENTRATION_MIN", 0.25),
        ("RISK_LARGE_PAYOUT_RELATIVE_FACTOR", 3.0),
    ],
)
def test_the_published_values_match_the_settings(name, value):
    assert getattr(settings, name) == value


def test_the_engine_is_deterministic_and_self_describing():
    engine = BehavioralTwinEngine(get_risk_config())
    assert engine.config.weight_new_device == EXPECTED_WEIGHTS["weight_new_device"]
    assert engine.config.threshold_isolated == EXPECTED_THRESHOLDS["threshold_isolated"]
