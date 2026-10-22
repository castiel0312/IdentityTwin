"""Unit tests for the deterministic behavioural twin risk engine.

The engine is a pure function of (request, twin baseline, session ledger). These
tests exercise it without a database so that every rule of the published risk
contract is pinned down independently of the HTTP layer.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.risk.config import get_risk_config
from app.risk.engine import BehavioralTwinEngine
from app.risk.schemas import (
    RiskEvaluationRequest,
    SessionRiskState,
    TwinSnapshot,
)
from app.risk.timezones import resolve_timezone
from app.risk.twin import device_is_known, hash_device, hash_recipient
from app.schemas.sessions import TrustLevel

MERCHANT_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
USER_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")

CONFIG = get_risk_config()
ENGINE = BehavioralTwinEngine(CONFIG)
TZ = resolve_timezone(CONFIG.default_timezone)

# The published signal weights. They are part of the risk contract and are
# asserted here so that an accidental re-tune fails the build.
CONTRACT_WEIGHTS = {
    "NEW_DEVICE": 18.0,
    "NEW_LOCATION": 14.0,
    "UNUSUAL_TIME": 11.0,
    "NEW_PAYEE": 16.0,
    "LARGE_PAYOUT": 21.0,
    "NEW_PAYEE_LARGE_PAYOUT": 9.0,
    "PAYEE_ADD_THEN_PAYOUT": 9.0,
    "CANARY_INTERACTION": 11.0,
}


def _local(moment: datetime) -> datetime:
    return moment.astimezone(TZ)


def _at(hour: int, day: int = 0) -> datetime:
    base = datetime(2026, 3, 2 + day, hour, 0, tzinfo=TZ)
    return base.astimezone(timezone.utc)


def _twin(**overrides) -> TwinSnapshot:
    """Return an established twin that already knows the default context."""
    twin = TwinSnapshot(merchant_id=MERCHANT_ID, user_id=USER_ID)
    twin.sample_count = 40
    twin.hour_histogram = {"10": 40}
    twin.total_amount = 4000.0
    twin.amount_count = 40
    twin.device_observations = {
        hash_device("device-known", CONFIG.device_hash_salt): 10,
    }
    twin.location_observations = {"BENGALURU": 10}
    twin.payee_observations = {hash_recipient("payee@example.test"): 10}
    return twin.model_copy(update=overrides)


def _state() -> SessionRiskState:
    return SessionRiskState(session_id=uuid.uuid4(), merchant_id=MERCHANT_ID, user_id=USER_ID)


def _request(**overrides) -> RiskEvaluationRequest:
    payload = {
        "session_id": uuid.uuid4(),
        "merchant_id": MERCHANT_ID,
        "user_id": USER_ID,
        "action_type": "auth.login",
        "amount": 0.0,
        "recipient": "",
        "context": {"location": "BENGALURU"},
        "occurred_at": _at(10),
        "event_id": uuid.uuid4(),
        "device_id": "device-known",
        "ip_address": "203.0.113.10",
        "event_type": "auth.login",
    }
    payload.update(overrides)
    return RiskEvaluationRequest(**payload)


# ---------------------------------------------------------------------------
# Contract: weights, thresholds and score bounds
# ---------------------------------------------------------------------------


def test_signal_weights_match_the_published_contract():
    assert CONFIG.weight_new_device == CONTRACT_WEIGHTS["NEW_DEVICE"]
    assert CONFIG.weight_new_location == CONTRACT_WEIGHTS["NEW_LOCATION"]
    assert CONFIG.weight_unusual_time == CONTRACT_WEIGHTS["UNUSUAL_TIME"]
    assert CONFIG.weight_new_payee == CONTRACT_WEIGHTS["NEW_PAYEE"]
    assert CONFIG.weight_large_payout == CONTRACT_WEIGHTS["LARGE_PAYOUT"]
    assert CONFIG.weight_new_payee_large_payout == CONTRACT_WEIGHTS["NEW_PAYEE_LARGE_PAYOUT"]
    assert CONFIG.weight_payee_add_then_payout == CONTRACT_WEIGHTS["PAYEE_ADD_THEN_PAYOUT"]
    assert CONFIG.weight_canary_interaction == CONTRACT_WEIGHTS["CANARY_INTERACTION"]


def test_trust_level_thresholds_match_the_prd_bands():
    assert CONFIG.threshold_restricted == 30.0
    assert CONFIG.threshold_decoy == 60.0
    assert CONFIG.threshold_isolated == 90.0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, TrustLevel.NORMAL),
        (29.9, TrustLevel.NORMAL),
        (30.0, TrustLevel.RESTRICTED),
        (59.9, TrustLevel.RESTRICTED),
        (60.0, TrustLevel.DECOY),
        (89.9, TrustLevel.DECOY),
        (90.0, TrustLevel.ISOLATED),
        (100.0, TrustLevel.ISOLATED),
    ],
)
def test_score_bands_map_to_the_expected_trust_level(score, expected):
    state = _state()
    state.current_score = score
    outcome = ENGINE.evaluate(_request(), _twin(), state, session_score=score, now=_at(10))
    assert outcome.result.evaluated_trust_level == expected
    assert 0.0 <= outcome.result.risk_score <= 100.0


def test_contributions_always_explain_the_raw_score():
    outcome = ENGINE.evaluate(
        _request(device_id="brand-new-device"), _twin(), _state(), now=_at(10)
    )
    signal_points = sum(c.points for c in outcome.result.contributions if c.kind == "signal")
    assert signal_points == outcome.result.raw_points_sum
    assert outcome.result.risk_signals["NEW_DEVICE"] == CONTRACT_WEIGHTS["NEW_DEVICE"]


# ---------------------------------------------------------------------------
# Server side derivation: client flags are ignored
# ---------------------------------------------------------------------------


def test_client_supplied_risk_flags_are_ignored():
    hostile_context = {
        "location": "BENGALURU",
        "is_new_device": True,
        "is_new_location": True,
        "is_unusual_time": True,
        "is_new_payee": True,
        "is_large_payout": True,
    }
    outcome = ENGINE.evaluate(
        _request(context=hostile_context, recipient="payee@example.test"),
        _twin(),
        _state(),
        now=_at(10),
    )
    assert outcome.result.risk_signals == {"BASELINE_ACTIVITY": 0.0}
    assert outcome.result.evaluated_trust_level == TrustLevel.NORMAL
    notes = outcome.result.features.notes
    assert "CLIENT_RISK_FLAG_IGNORED:device" in notes
    assert "CLIENT_RISK_FLAG_IGNORED:location" in notes
    assert "CLIENT_RISK_FLAG_IGNORED:time" in notes
    assert "CLIENT_RISK_FLAG_IGNORED:payee" in notes
    assert "CLIENT_RISK_FLAG_IGNORED:large_payout" in notes


def test_a_client_cannot_assert_a_canary_hit():
    outcome = ENGINE.evaluate(
        _request(context={"location": "BENGALURU", "is_canary": True}),
        _twin(),
        _state(),
        now=_at(10),
    )
    assert outcome.result.evaluated_trust_level == TrustLevel.NORMAL
    assert "CANARY_INTERACTION" not in outcome.result.risk_signals


# ---------------------------------------------------------------------------
# Latching, decay and sequences
# ---------------------------------------------------------------------------


def test_session_scoped_signals_fire_once_per_session():
    twin = _twin()
    state = _state()
    request = _request(device_id="brand-new-device")

    first = ENGINE.evaluate(request, twin, state, now=_at(10))
    second = ENGINE.evaluate(request, twin, state, now=_at(10, day=1))

    assert first.result.risk_signals["NEW_DEVICE"] == 18.0
    assert "NEW_DEVICE" not in second.result.risk_signals
    assert second.result.raw_points_sum == 0.0


def test_behavioural_decay_removes_transient_points():
    twin = _twin()
    state = _state()

    flagged = ENGINE.evaluate(
        _request(action_type="payout.submit", amount=9_000.0),
        twin,
        state,
        now=_at(10),
    )
    assert flagged.result.risk_score == 21.0

    decayed = ENGINE.evaluate(
        _request(event_id=uuid.uuid4()),
        twin,
        state,
        now=_at(10),
    )
    assert decayed.result.risk_score == 16.0
    decay = [c for c in decayed.result.contributions if c.kind == "decay"]
    assert decay and decay[0].points == -CONFIG.decay_points_per_event


def test_decay_is_blocked_while_the_session_holds_anomaly_evidence():
    twin = _twin()
    state = _state()
    ENGINE.evaluate(_request(device_id="brand-new-device"), twin, state, now=_at(10))
    follow_up = ENGINE.evaluate(
        _request(device_id="brand-new-device", event_id=uuid.uuid4()),
        twin,
        state,
        now=_at(10),
    )
    decay = [c for c in follow_up.result.contributions if c.kind == "decay"]
    assert decay == []
    assert follow_up.result.risk_score == 18.0


def test_canary_evidence_is_never_decayed():
    twin = _twin()
    state = _state()
    canary = ENGINE.evaluate(
        _request(
            action_type="canary.trap",
            event_type="security.anomaly_detected",
            context={"location": "BENGALURU", "canary_token": "IT-CANARY-0001"},
        ),
        twin,
        state,
        now=_at(10),
    )
    assert canary.result.evaluated_trust_level == TrustLevel.ISOLATED
    assert canary.result.risk_score >= CONFIG.threshold_isolated
    assert "CANARY_INTERACTION_LEVEL_3_OVERRIDE" in canary.result.reason_codes
    floor = [c for c in canary.result.contributions if c.kind == "isolation_floor"]
    assert floor, "the isolation floor must be an explicit contribution"

    follow_up = ENGINE.evaluate(_request(event_id=uuid.uuid4()), twin, state, now=_at(10))
    decay = [c for c in follow_up.result.contributions if c.kind == "decay"]
    assert decay == []


def test_payee_add_then_payout_sequence_is_detected():
    twin = _twin()
    state = _state()
    ENGINE.evaluate(
        _request(
            action_type="payee.add",
            event_type="payee.added",
            recipient="payee@example.test",
        ),
        twin,
        state,
        now=_at(10),
    )
    payout = ENGINE.evaluate(
        _request(
            action_type="payout.submit",
            event_type="payout.submit",
            recipient="payee@example.test",
            amount=100.0,
            event_id=uuid.uuid4(),
        ),
        twin,
        state,
        now=_at(10),
    )
    assert payout.result.risk_signals["PAYEE_ADD_THEN_PAYOUT"] == 9.0


def test_duplicate_events_are_ignored():
    twin = _twin()
    state = _state()
    request = _request(device_id="brand-new-device")
    first = ENGINE.evaluate(request, twin, state, now=_at(10))
    second = ENGINE.evaluate(request, twin, state, now=_at(10))
    assert second.result.duplicate_event is True
    assert second.result.risk_score == first.result.risk_score
    assert second.result.raw_points_sum == 0.0


# ---------------------------------------------------------------------------
# Twin learning rules
# ---------------------------------------------------------------------------


def test_an_attack_session_does_not_teach_the_twin():
    twin = _twin()
    state = _state()
    outcome = ENGINE.evaluate(
        _request(device_id="attacker-device", recipient="evil@example.test"),
        twin,
        state,
        now=_at(3),
    )
    attacker_device = hash_device("attacker-device", CONFIG.device_hash_salt)
    assert attacker_device not in twin.device_observations
    assert outcome.twin.device_observations.get(attacker_device, 0) == 0
    assert twin.confirmed_devices == []


def test_clean_activity_teaches_the_twin():
    twin = _twin()
    state = _state()
    outcome = ENGINE.evaluate(_request(), twin, state, now=_at(10))
    assert outcome.twin.sample_count == twin.sample_count + 1
    assert outcome.twin.hour_histogram["10"] == twin.hour_histogram["10"] + 1
    assert outcome.twin.device_observations


def test_a_new_device_is_confirmed_after_the_confirmation_threshold():
    twin = _twin()
    engine = BehavioralTwinEngine(CONFIG)
    for index in range(CONFIG.context_confirm_observations):
        outcome = engine.evaluate(
            _request(device_id="second-device", event_id=uuid.uuid4()),
            twin,
            _state(),
            now=_at(10, day=index),
        )
        twin = outcome.twin
    assert len(twin.confirmed_devices) == 1
    assert device_is_known(twin, twin.confirmed_devices[0], CONFIG)


def test_the_hour_signal_needs_a_concentrated_time_profile():
    broad = _twin(hour_histogram={str(hour): 4 for hour in range(8, 20)})
    outcome = ENGINE.evaluate(_request(occurred_at=_at(3)), broad, _state(), now=_at(3))
    assert "UNUSUAL_TIME" not in outcome.result.risk_signals

    narrow = _twin(hour_histogram={"10": 40})
    outcome = ENGINE.evaluate(_request(occurred_at=_at(3)), narrow, _state(), now=_at(3))
    assert outcome.result.risk_signals["UNUSUAL_TIME"] == 11.0


def test_a_large_payout_is_relative_to_the_identity():
    # The twin already knows large payouts, so the absolute threshold alone
    # must not fire.
    large_payout_identity = _twin(total_amount=150_000.0, amount_count=10)
    outcome = ENGINE.evaluate(
        _request(action_type="payout.submit", amount=20_000.0),
        large_payout_identity,
        _state(),
        now=_at(10),
    )
    assert "LARGE_PAYOUT" not in outcome.result.risk_signals

    # A payout that spikes far above the identity average does fire.
    outcome = ENGINE.evaluate(
        _request(action_type="payout.submit", amount=90_000.0),
        large_payout_identity,
        _state(),
        now=_at(10),
    )
    assert outcome.result.risk_signals["LARGE_PAYOUT"] == 21.0


def test_provisional_twins_attenuate_newness_signals():
    provisional = TwinSnapshot(merchant_id=MERCHANT_ID, user_id=USER_ID)
    outcome = ENGINE.evaluate(
        _request(device_id="brand-new-device"),
        provisional,
        _state(),
        now=_at(10),
    )
    expected = round(CONTRACT_WEIGHTS["NEW_DEVICE"] * CONFIG.provisional_factor, 4)
    assert outcome.result.risk_signals["NEW_DEVICE"] == expected


def test_time_based_learning_uses_the_merchant_timezone():
    twin = _twin(hour_histogram={"3": 40})
    # 22:00 UTC is 03:30 in Asia/Kolkata, the merchant local time.
    moment = datetime(2026, 3, 2, 22, 0, tzinfo=timezone.utc)
    assert _local(moment).hour == 3
    outcome = ENGINE.evaluate(_request(occurred_at=moment), twin, _state(), now=moment)
    assert "UNUSUAL_TIME" not in outcome.result.risk_signals


def test_evaluation_is_deterministic():
    twin = _twin()
    request = _request(device_id="brand-new-device")
    first = ENGINE.evaluate(request, twin, _state(), now=_at(10))
    second = ENGINE.evaluate(request, twin, _state(), now=_at(10))
    assert first.result.risk_score == second.result.risk_score
    assert first.result.risk_signals == second.result.risk_signals
    assert first.result.reason_codes == second.result.reason_codes


def test_time_decay_uses_the_supplied_timestamp_only():
    twin = _twin()
    state = _state()
    start = _at(10)
    ENGINE.evaluate(_request(device_id="brand-new-device"), twin, state, now=start)
    later = start + timedelta(hours=5)
    outcome = ENGINE.evaluate(
        _request(device_id="brand-new-device", event_id=uuid.uuid4()),
        twin,
        state,
        now=later,
    )
    assert outcome.result.risk_score == 18.0
