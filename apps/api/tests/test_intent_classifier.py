from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.intent.classifier import classify_intent
from app.intent.signals import extract_intent_signals
from app.intent.taxonomy import (
    ConfidenceReason,
    IntentConfidence,
    IntentEvidenceSource,
    IntentHypothesis,
    IntentSignalCode,
)
from app.schemas.intent import (
    CanaryObservation,
    IntentEvidenceReference,
    IntentSignals,
    IntentSourceData,
    SessionObservation,
)

SESSION_ID = UUID("00000000-0000-0000-0000-000000000001")
BASE = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)


def signals(**overrides) -> IntentSignals:
    values = {
        "session_id": SESSION_ID,
        "baseline_ready": True,
        "has_payout_activity": True,
        "event_count": 3,
        "last_event_at": BASE,
    }
    values.update(overrides)
    if "baseline_provisional" not in overrides:
        values["baseline_provisional"] = not values["baseline_ready"]
    return IntentSignals(**values)


def reference(
    *codes: IntentSignalCode,
    ref_id: str = "evidence-1",
) -> IntentEvidenceReference:
    return IntentEvidenceReference(
        source=IntentEvidenceSource.EVENT,
        ref_id=ref_id,
        summary="Structured evidence.",
        occurred_at=BASE,
        signal_codes=list(codes),
    )


def test_unknown_when_no_supported_evidence() -> None:
    analysis = classify_intent(
        signals(
            baseline_ready=False,
            has_payout_activity=False,
            event_count=0,
            last_event_at=None,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE
    assert analysis.confidence is IntentConfidence.UNKNOWN
    assert ConfidenceReason.NO_SUPPORTING_EVIDENCE in analysis.confidence_basis
    assert ConfidenceReason.BASELINE_PROVISIONAL in analysis.confidence_basis
    assert analysis.abstention_reason is not None
    assert "No supported events" in analysis.abstention_reason
    assert analysis.evidence
    assert analysis.advisory_only is True
    assert analysis.requires_human_approval is True


def test_provisional_baseline_blocks_novelty_based_takeover() -> None:
    analysis = classify_intent(
        signals(
            baseline_ready=False,
            has_payout_activity=False,
            has_new_device=True,
            has_new_location=True,
            has_unusual_time=True,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE
    assert analysis.confidence is IntentConfidence.UNKNOWN


def test_canary_containment_is_high_confidence() -> None:
    analysis = classify_intent(
        signals(
            has_canary_interaction=True,
            evidence=[reference(IntentSignalCode.CANARY_INTERACTION)],
        )
    )

    assert analysis.primary_intent is IntentHypothesis.CONTAINMENT_PROBING
    assert analysis.confidence is IntentConfidence.HIGH
    assert ConfidenceReason.CANARY_EVIDENCE in analysis.confidence_basis
    assert analysis.secondary_intents == []


def test_repeated_blocked_payouts_are_medium_confidence_containment() -> None:
    analysis = classify_intent(signals(blocked_payout_count=2))

    assert analysis.primary_intent is IntentHypothesis.CONTAINMENT_PROBING
    assert analysis.confidence is IntentConfidence.MEDIUM
    assert ConfidenceReason.REPEATED_CONTAINMENT_EVIDENCE in analysis.confidence_basis


def test_decoy_and_blocked_payout_is_high_confidence_containment() -> None:
    analysis = classify_intent(signals(has_decoy_routing=True, blocked_payout_count=1))

    assert analysis.primary_intent is IntentHypothesis.CONTAINMENT_PROBING
    assert analysis.confidence is IntentConfidence.HIGH


def test_account_takeover_requires_two_independent_signals() -> None:
    analysis = classify_intent(
        signals(has_new_device=True, has_unusual_time=True, has_payout_activity=False)
    )

    assert analysis.primary_intent is IntentHypothesis.ACCOUNT_TAKEOVER
    assert analysis.confidence is IntentConfidence.MEDIUM
    assert ConfidenceReason.TWO_INDEPENDENT_SIGNALS in analysis.confidence_basis
    assert ConfidenceReason.BASELINE_MATURE in analysis.confidence_basis


def test_account_takeover_is_high_with_three_signals() -> None:
    analysis = classify_intent(
        signals(
            has_new_device=True,
            has_new_location=True,
            security_anomaly_count=1,
            has_payout_activity=False,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.ACCOUNT_TAKEOVER
    assert analysis.confidence is IntentConfidence.HIGH
    assert ConfidenceReason.THREE_OR_MORE_INDEPENDENT_SIGNALS in analysis.confidence_basis


def test_payee_redirection_is_high_with_sequence_and_large_payout() -> None:
    analysis = classify_intent(
        signals(
            has_payee_add_then_payout=True,
            has_large_payout=True,
            has_new_payee=True,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.PAYEE_REDIRECTION
    assert analysis.confidence is IntentConfidence.HIGH
    assert ConfidenceReason.HIGH_SPECIFICITY_SEQUENCE in analysis.confidence_basis
    assert ConfidenceReason.TWO_INDEPENDENT_SIGNALS in analysis.confidence_basis


def test_payee_redirection_is_medium_from_new_payee_and_large_payout() -> None:
    analysis = classify_intent(signals(has_new_payee=True, has_large_payout=True))

    assert analysis.primary_intent is IntentHypothesis.PAYEE_REDIRECTION
    assert analysis.confidence is IntentConfidence.MEDIUM
    assert analysis.confidence_basis == [ConfidenceReason.TWO_INDEPENDENT_SIGNALS]


def test_velocity_abuse_is_high_when_registration_and_payout_velocity_cooccur() -> None:
    analysis = classify_intent(
        signals(
            has_payee_registration_velocity=True,
            has_payout_velocity=True,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.VELOCITY_ABUSE
    assert analysis.confidence is IntentConfidence.HIGH
    assert ConfidenceReason.TWO_INDEPENDENT_SIGNALS in analysis.confidence_basis


def test_velocity_abuse_is_medium_with_one_velocity_signal() -> None:
    analysis = classify_intent(signals(has_payee_registration_velocity=True))

    assert analysis.primary_intent is IntentHypothesis.VELOCITY_ABUSE
    assert analysis.confidence is IntentConfidence.MEDIUM
    assert analysis.confidence_basis == [ConfidenceReason.SINGLE_WEAK_SIGNAL]


def test_routine_requires_mature_baseline_payout_activity_and_no_anomalies() -> None:
    analysis = classify_intent(signals())

    assert analysis.primary_intent is IntentHypothesis.ROUTINE_PAYMENT_OPERATION
    assert analysis.confidence is IntentConfidence.LOW
    assert ConfidenceReason.ABSENCE_OF_ANOMALY_IS_NOT_PROOF in analysis.confidence_basis
    assert analysis.abstention_reason is None


def test_routine_is_not_selected_when_any_supported_anomaly_exists() -> None:
    analysis = classify_intent(signals(has_new_payee=True))

    assert analysis.primary_intent is IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE


def test_secondary_hypotheses_are_limited_to_two_and_evidence_is_bounded() -> None:
    evidence = [
        reference(IntentSignalCode.CANARY_INTERACTION, ref_id=f"evidence-{index}")
        for index in range(20)
    ]
    analysis = classify_intent(
        signals(
            has_canary_interaction=True,
            has_new_device=True,
            has_new_location=True,
            has_unusual_time=True,
            has_payee_add_then_payout=True,
            has_new_payee=True,
            has_large_payout=True,
            has_payee_registration_velocity=True,
            has_payout_velocity=True,
            evidence=evidence,
        )
    )

    assert analysis.primary_intent is IntentHypothesis.CONTAINMENT_PROBING
    assert analysis.secondary_intents == [
        IntentHypothesis.ACCOUNT_TAKEOVER,
        IntentHypothesis.PAYEE_REDIRECTION,
    ]
    assert len(analysis.evidence) <= 12


def test_analysis_has_no_percentages_and_is_advisory() -> None:
    analysis = classify_intent(signals())
    serialized = analysis.model_dump_json()

    assert "%" not in serialized
    assert analysis.advisory_only is True
    assert analysis.requires_human_approval is True
    assert analysis.classifier_version == "intent-classifier-v1"


def test_extracted_canary_signal_flows_to_classifier() -> None:
    source = IntentSourceData(
        session=SessionObservation(session_id=SESSION_ID, last_activity_at=BASE),
        canaries=[
            CanaryObservation(
                canary_id=uuid4(),
                kind="payout",
                armed=True,
                triggered_at=BASE,
            )
        ],
    )

    analysis = classify_intent(extract_intent_signals(source))

    assert analysis.primary_intent is IntentHypothesis.CONTAINMENT_PROBING
    assert analysis.confidence is IntentConfidence.HIGH
    assert any(
        IntentSignalCode.CANARY_INTERACTION in item.signal_codes for item in analysis.evidence
    )
