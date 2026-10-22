"""Tests for the synthetic dataset and the calibration harness.

The synthetic dataset is the evidence base of the calibration report, so its
determinism and its coverage are part of the contract of this deliverable.
"""

import json
from pathlib import Path

import pytest

from app.core.config import settings
from app.risk.calibration import (
    CALIBRATION_NAMESPACE,
    HOLDOUT_FRACTION,
    _replay_identity,
    run_calibration,
    split_identities,
)
from app.risk.config import get_risk_config
from app.risk.engine import BehavioralTwinEngine
from app.risk.synthetic_data import (
    ATTACK_TYPES,
    COHORT_SIZES,
    TOTAL_IDENTITIES,
    build_profiles,
    event_time,
    expand_profile,
    fixture_digest,
    profile_fixture,
    profiles_from_fixture,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[4] / "data" / "synthetic" / "synthetic_identities.json"
)


def test_the_dataset_has_the_promised_size():
    assert TOTAL_IDENTITIES == 1284
    assert sum(COHORT_SIZES.values()) == TOTAL_IDENTITIES
    profiles = build_profiles(settings.RISK_SYNTHETIC_SEED)
    assert len(profiles) == TOTAL_IDENTITIES
    assert len({profile.identity_id for profile in profiles}) == TOTAL_IDENTITIES


def test_every_cohort_is_represented():
    profiles = build_profiles(settings.RISK_SYNTHETIC_SEED)
    counts: dict[str, int] = {}
    for profile in profiles:
        counts[profile.cohort] = counts.get(profile.cohort, 0) + 1
    assert counts == COHORT_SIZES


def test_every_attack_type_is_represented():
    profiles = build_profiles(settings.RISK_SYNTHETIC_SEED)
    attacks = {profile.attack.attack_type for profile in profiles if profile.attack is not None}
    assert attacks == set(ATTACK_TYPES)


def test_the_dataset_is_deterministic():
    first = build_profiles(settings.RISK_SYNTHETIC_SEED)
    second = build_profiles(settings.RISK_SYNTHETIC_SEED)
    assert [profile.model_dump() for profile in first] == [
        profile.model_dump() for profile in second
    ]

    profile = first[0]
    assert [event.model_dump() for event in _events(profile)] == [
        event.model_dump() for event in _events(profile)
    ]


def _events(profile):
    for session in expand_profile(profile, settings.RISK_SYNTHETIC_SEED):
        yield from session.events


def test_the_committed_fixture_matches_the_generator():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert payload["seed"] == settings.RISK_SYNTHETIC_SEED
    assert payload["total_identities"] == TOTAL_IDENTITIES
    assert fixture_digest(payload) == fixture_digest(profile_fixture(settings.RISK_SYNTHETIC_SEED))


def test_the_fixture_round_trips_into_profiles():
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    profiles = profiles_from_fixture(payload)
    assert len(profiles) == TOTAL_IDENTITIES
    assert profiles[0].identity_id == payload["identities"][0]["identity_id"]


def test_the_split_is_deterministic_and_disjoint():
    profiles = build_profiles(settings.RISK_SYNTHETIC_SEED)
    calibration, holdout = split_identities(profiles, settings.RISK_SYNTHETIC_SEED)
    again_calibration, again_holdout = split_identities(profiles, settings.RISK_SYNTHETIC_SEED)
    assert [p.identity_id for p in calibration] == [p.identity_id for p in again_calibration]
    assert [p.identity_id for p in holdout] == [p.identity_id for p in again_holdout]
    assert not {p.identity_id for p in calibration} & {p.identity_id for p in holdout}
    assert len(calibration) + len(holdout) == TOTAL_IDENTITIES
    assert len(holdout) == round(TOTAL_IDENTITIES * HOLDOUT_FRACTION)


def test_a_compromised_identity_is_detected_and_a_benign_one_is_not():
    config = get_risk_config()
    engine = BehavioralTwinEngine(config)
    profiles = build_profiles(settings.RISK_SYNTHETIC_SEED)

    attacker = next(
        profile
        for profile in profiles
        if profile.attack is not None and profile.attack.attack_type == "device_takeover"
    )
    sessions = expand_profile(attacker, settings.RISK_SYNTHETIC_SEED)
    outcome = _replay_identity(attacker, sessions, engine, config)
    assert outcome.detected is True
    assert outcome.label == "compromised"

    benign = next(profile for profile in profiles if profile.cohort == "regular")
    sessions = expand_profile(benign, settings.RISK_SYNTHETIC_SEED)
    outcome = _replay_identity(benign, sessions, engine, config)
    assert outcome.detected is False
    assert outcome.flagged_sessions == 0


def test_the_calibration_namespace_is_stable():
    assert CALIBRATION_NAMESPACE is not None
    assert len(str(CALIBRATION_NAMESPACE)) > 0
    assert event_time(0).tzinfo is not None


@pytest.mark.slow
def test_the_full_calibration_run_reports_bounded_metrics():
    report = run_calibration(settings.RISK_SYNTHETIC_SEED)
    for metrics in (report.calibration, report.holdout):
        assert 0.0 <= metrics.false_positive_rate <= 0.05
        assert 0.0 <= metrics.detection_rate <= 1.0
        assert metrics.benign_sessions > 0
        assert metrics.compromised_identities > 0
    # Every attack type except the documented slow and low pattern is detected.
    for attack_type, data in report.calibration.per_attack_type.items():
        if attack_type == "slow_and_low":
            continue
        assert data["detected"] == data["identities"], attack_type
