from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from app.intent.signals import extract_intent_signals, normalize_event_type
from app.intent.taxonomy import IntentSignalCode
from app.schemas.intent import (
    CanaryObservation,
    EventObservation,
    IntentExtractionPolicy,
    IntentSourceData,
    PayoutObservation,
    SequenceMarkerObservation,
    SessionObservation,
    SessionRiskStateObservation,
    TwinBaselineObservation,
)

BASE = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")


def event(
    event_type: str,
    *,
    occurred_at: datetime = BASE,
    action: str = "",
    device_hash: str | None = None,
    location_bucket: str | None = None,
    recipient_hash: str | None = None,
) -> EventObservation:
    return EventObservation(
        event_id=uuid4(),
        event_type=event_type,
        action=action,
        occurred_at=occurred_at,
        server_received_at=occurred_at,
        device_hash=device_hash,
        location_bucket=location_bucket,
        recipient_hash=recipient_hash,
    )


def twin(**overrides) -> TwinBaselineObservation:
    values = {
        "sample_count": 12,
        "amount_count": 10,
        "total_amount": 10_000.0,
        "device_observations": {"device-known": 4},
        "location_observations": {"location-known": 4},
        "payee_observations": {"payee-known": 4},
        "hour_histogram": {"15": 12},
    }
    values.update(overrides)
    return TwinBaselineObservation(**values)


def session(**overrides) -> SessionObservation:
    values = {
        "session_id": SESSION_ID,
        "trust_level": "NORMAL",
        "status": "active",
        "risk_score": 0.0,
        "last_activity_at": BASE,
    }
    values.update(overrides)
    return SessionObservation(**values)


def payout(
    amount: float = 100.0,
    *,
    status: str = "completed",
    provider_name: str | None = None,
    created_at: datetime = BASE,
) -> PayoutObservation:
    return PayoutObservation(
        payout_id=uuid4(),
        amount=amount,
        status=status,
        provider_name=provider_name,
        created_at=created_at,
        executed_at=created_at,
    )


def source(**overrides) -> IntentSourceData:
    values = {
        "session": session(),
        "events": [],
        "twin": None,
        "risk_state": None,
        "payouts": [],
        "canaries": [],
        "incidents": [],
    }
    values.update(overrides)
    return IntentSourceData(**values)


def evidence_codes(signals) -> set[IntentSignalCode]:
    return {code for reference in signals.evidence for code in reference.signal_codes}


def test_normalizes_known_aliases_and_counts_unknown_event_types() -> None:
    signals = extract_intent_signals(
        source(
            events=[
                event("login"),
                event("payout", occurred_at=BASE + timedelta(minutes=1)),
                event("payee_added", occurred_at=BASE + timedelta(minutes=2)),
                event("unrecognized.event", occurred_at=BASE + timedelta(minutes=3)),
            ]
        )
    )

    assert signals.event_count == 4
    assert signals.auth_event_count == 1
    assert signals.payout_event_count == 1
    assert signals.payee_registration_count == 1
    assert signals.unknown_event_count == 1
    assert normalize_event_type("login") == "auth.login"
    assert normalize_event_type("unrecognized.event") == "unknown"


def test_provisional_baseline_does_not_infer_novelty() -> None:
    signals = extract_intent_signals(
        source(
            twin=twin(sample_count=3),
            events=[
                event(
                    "auth.login",
                    device_hash="device-new",
                    location_bucket="location-new",
                    recipient_hash="payee-new",
                )
            ],
            payouts=[payout(6000.0)],
        )
    )

    assert signals.baseline_ready is False
    assert signals.baseline_provisional is True
    assert signals.has_new_device is False
    assert signals.has_new_location is False
    assert signals.has_new_payee is False
    assert signals.has_unusual_time is False
    assert signals.has_large_payout is True


def test_mature_baseline_detects_novelty_large_payout_and_evidence() -> None:
    signals = extract_intent_signals(
        source(
            twin=twin(),
            events=[
                event(
                    "payout.submit",
                    device_hash="device-new",
                    location_bucket="location-new",
                    recipient_hash="payee-new",
                )
            ],
            payouts=[payout(6000.0)],
        )
    )

    assert signals.baseline_ready is True
    assert signals.has_new_device is True
    assert signals.has_new_location is True
    assert signals.has_new_payee is True
    assert signals.has_unusual_time is False
    assert signals.has_large_payout is True
    codes = evidence_codes(signals)
    assert IntentSignalCode.NEW_DEVICE in codes
    assert IntentSignalCode.NEW_LOCATION in codes
    assert IntentSignalCode.NEW_PAYEE in codes
    assert IntentSignalCode.LARGE_PAYOUT in codes


def test_large_payout_respects_relative_baseline_rule() -> None:
    signals = extract_intent_signals(
        source(
            twin=twin(amount_count=10, total_amount=30_000.0),
            payouts=[payout(6000.0)],
        )
    )

    assert signals.has_large_payout is False


@pytest.mark.parametrize(
    ("offset_seconds", "recipient_hash", "expected"),
    [
        (600, "payee-a", True),
        (2000, "payee-a", False),
        (600, "payee-b", False),
    ],
)
def test_payee_add_then_payout_requires_same_payee_and_window(
    offset_seconds: int,
    recipient_hash: str,
    expected: bool,
) -> None:
    signals = extract_intent_signals(
        source(
            events=[
                event("payee.added", recipient_hash="payee-a"),
                event(
                    "payout.submit",
                    occurred_at=BASE + timedelta(seconds=offset_seconds),
                    recipient_hash=recipient_hash,
                ),
            ]
        )
    )

    assert signals.has_payee_add_then_payout is expected


def test_velocity_uses_largest_window_count() -> None:
    events = []
    for index in range(3):
        events.append(
            event(
                "payee.added",
                occurred_at=BASE + timedelta(seconds=index * 60),
                recipient_hash=f"payee-{index}",
            )
        )
        events.append(
            event(
                "payout.submit",
                occurred_at=BASE + timedelta(seconds=300 + index * 60),
                recipient_hash=f"payee-{index}",
            )
        )

    signals = extract_intent_signals(source(events=events))

    assert signals.has_payee_registration_velocity is True
    assert signals.has_payout_velocity is True
    assert signals.max_payee_registrations_in_window == 3
    assert signals.max_payouts_in_window == 3


def test_canary_decoy_and_blocked_payout_signals() -> None:
    signals = extract_intent_signals(
        source(
            payouts=[
                payout(status="decoy_completed"),
                payout(status="blocked"),
                payout(status="provider_denied"),
            ],
            canaries=[
                CanaryObservation(
                    canary_id=uuid4(),
                    kind="payout",
                    armed=True,
                    triggered_at=BASE,
                )
            ],
        )
    )

    assert signals.has_canary_interaction is True
    assert signals.has_decoy_routing is True
    assert signals.blocked_payout_count == 2
    codes = evidence_codes(signals)
    assert IntentSignalCode.CANARY_INTERACTION in codes
    assert IntentSignalCode.DECOY_ROUTING in codes
    assert IntentSignalCode.BLOCKED_PAYOUT in codes


def test_consumed_sequence_marker_detects_sequence_outside_event_window() -> None:
    signals = extract_intent_signals(
        source(
            events=[
                event("payee.added", recipient_hash="payee-a"),
                event(
                    "payout.submit",
                    occurred_at=BASE + timedelta(hours=1),
                    recipient_hash="payee-a",
                ),
            ],
            risk_state=SessionRiskStateObservation(
                sequence_markers=[
                    SequenceMarkerObservation(
                        marker_id="marker-1",
                        sequence_type="payee_add_then_payout",
                        recipient_hash="payee-a",
                        occurred_at=BASE,
                    )
                ],
                consumed_markers=["marker-1"],
                last_evaluated_at=BASE,
            ),
        )
    )

    assert signals.has_payee_add_then_payout is True
    assert IntentSignalCode.PAYEE_ADD_THEN_PAYOUT in evidence_codes(signals)


def test_unusual_time_requires_established_concentrated_hour_baseline() -> None:
    habitual = extract_intent_signals(
        source(
            twin=twin(hour_histogram={"3": 10, "4": 1}),
            events=[
                event(
                    "session.heartbeat",
                    occurred_at=datetime(2026, 1, 1, 21, 30, tzinfo=timezone.utc),
                    device_hash="device-known",
                    location_bucket="location-known",
                )
            ],
        )
    )
    unusual = extract_intent_signals(
        source(
            twin=twin(hour_histogram={"3": 10, "4": 1}),
            events=[
                event(
                    "session.heartbeat",
                    occurred_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
                    device_hash="device-known",
                    location_bucket="location-known",
                )
            ],
        )
    )

    assert habitual.has_unusual_time is False
    assert unusual.has_unusual_time is True
    assert unusual.hour_baseline_ready is True


def test_extraction_is_bounded_by_policy() -> None:
    signals = extract_intent_signals(
        source(
            events=[
                event("auth.login", occurred_at=BASE),
                event("auth.login", occurred_at=BASE + timedelta(seconds=1)),
                event("auth.login", occurred_at=BASE + timedelta(seconds=2)),
            ]
        ),
        IntentExtractionPolicy(max_events=2),
    )

    assert signals.event_count == 2
    assert signals.auth_event_count == 2


def test_evidence_does_not_expose_raw_hashes_or_actions() -> None:
    signals = extract_intent_signals(
        source(
            twin=twin(),
            events=[
                event(
                    "unrecognized.event",
                    action="secret-action",
                    device_hash="secret-device-hash",
                    location_bucket="secret-location-bucket",
                    recipient_hash="secret-recipient-hash",
                )
            ],
        )
    )

    serialized = signals.model_dump_json()
    assert "secret-device-hash" not in serialized
    assert "secret-location-bucket" not in serialized
    assert "secret-recipient-hash" not in serialized
    assert "secret-action" not in serialized
