"""Deterministic, evidence-backed intent classification.

The classifier is a pure function of :class:`IntentSignals`. It never calls a
model, the risk engine, the gateway or a database. Confidence is intentionally
ordinal; a percentage would imply a calibrated probability that this system
cannot currently support.
"""

from dataclasses import dataclass

from app.intent.taxonomy import (
    ConfidenceReason,
    IntentConfidence,
    IntentEvidenceSource,
    IntentHypothesis,
    IntentSignalCode,
)
from app.schemas.intent import (
    IntentAnalysis,
    IntentEvidenceReference,
    IntentSignals,
)

_CLASSIFIER_VERSION = "intent-classifier-v1"

_BASE_LIMITATIONS = [
    "Intent hypotheses are advisory and cannot change risk scores, routing, access or payments.",
    "Absence of a recorded signal is not proof of benign intent.",
    "The profiler does not use raw device identifiers, IP addresses, recipient addresses, "
    "event metadata, incident free text or AI Investigator narratives.",
    "Keystroke dynamics, mouse dynamics, page content and confirmed fraud labels are unavailable.",
    "Confidence is an ordinal band, not a probability.",
]


@dataclass(frozen=True)
class _HypothesisMatch:
    hypothesis: IntentHypothesis
    confidence: IntentConfidence
    basis: list[ConfidenceReason]
    signal_codes: frozenset[IntentSignalCode]


def _containment_match(signals: IntentSignals) -> _HypothesisMatch | None:
    repeated_blocks = signals.blocked_payout_count >= 2
    blocked_with_anomaly = signals.blocked_payout_count > 0 and signals.security_anomaly_count > 0
    if not (
        signals.has_canary_interaction
        or signals.has_decoy_routing
        or repeated_blocks
        or blocked_with_anomaly
    ):
        return None

    basis: list[ConfidenceReason] = []
    if signals.has_canary_interaction:
        basis.append(ConfidenceReason.CANARY_EVIDENCE)
    if signals.has_decoy_routing or signals.blocked_payout_count > 0:
        basis.append(ConfidenceReason.CONTAINMENT_EVIDENCE)
    if repeated_blocks:
        basis.append(ConfidenceReason.REPEATED_CONTAINMENT_EVIDENCE)

    if signals.has_canary_interaction or (
        signals.has_decoy_routing and signals.blocked_payout_count > 0
    ):
        confidence = IntentConfidence.HIGH
    else:
        confidence = IntentConfidence.MEDIUM

    return _HypothesisMatch(
        hypothesis=IntentHypothesis.CONTAINMENT_PROBING,
        confidence=confidence,
        basis=basis,
        signal_codes=frozenset(
            {
                IntentSignalCode.CANARY_INTERACTION,
                IntentSignalCode.DECOY_ROUTING,
                IntentSignalCode.BLOCKED_PAYOUT,
                IntentSignalCode.EVENT_SECURITY_ANOMALY,
            }
        ),
    )


def _takeover_match(signals: IntentSignals) -> _HypothesisMatch | None:
    if not signals.baseline_ready:
        return None

    device_trigger = signals.has_new_device and (
        signals.has_new_location
        or signals.has_unusual_time
        or signals.security_anomaly_count > 0
        or signals.mfa_event_count > 0
    )
    location_trigger = signals.has_new_location and (
        signals.has_unusual_time or signals.security_anomaly_count > 0
    )
    if not (device_trigger or location_trigger):
        return None

    supporting_count = sum(
        (
            int(signals.has_new_device),
            int(signals.has_new_location),
            int(signals.has_unusual_time),
            int(signals.security_anomaly_count > 0),
            int(signals.mfa_event_count > 0),
        )
    )
    if supporting_count >= 3:
        confidence = IntentConfidence.HIGH
        basis = [
            ConfidenceReason.THREE_OR_MORE_INDEPENDENT_SIGNALS,
            ConfidenceReason.BASELINE_MATURE,
        ]
    else:
        confidence = IntentConfidence.MEDIUM
        basis = [
            ConfidenceReason.TWO_INDEPENDENT_SIGNALS,
            ConfidenceReason.BASELINE_MATURE,
        ]

    return _HypothesisMatch(
        hypothesis=IntentHypothesis.ACCOUNT_TAKEOVER,
        confidence=confidence,
        basis=basis,
        signal_codes=frozenset(
            {
                IntentSignalCode.NEW_DEVICE,
                IntentSignalCode.NEW_LOCATION,
                IntentSignalCode.UNUSUAL_TIME,
                IntentSignalCode.EVENT_SECURITY_ANOMALY,
                IntentSignalCode.EVENT_MFA,
            }
        ),
    )


def _payee_redirection_match(signals: IntentSignals) -> _HypothesisMatch | None:
    if not (
        signals.has_payee_add_then_payout or (signals.has_new_payee and signals.has_large_payout)
    ):
        return None

    if signals.has_payee_add_then_payout and (signals.has_large_payout or signals.has_new_payee):
        confidence = IntentConfidence.HIGH
        basis = [
            ConfidenceReason.HIGH_SPECIFICITY_SEQUENCE,
            ConfidenceReason.TWO_INDEPENDENT_SIGNALS,
        ]
    elif signals.has_payee_add_then_payout:
        confidence = IntentConfidence.MEDIUM
        basis = [ConfidenceReason.HIGH_SPECIFICITY_SEQUENCE]
    else:
        confidence = IntentConfidence.MEDIUM
        basis = [ConfidenceReason.TWO_INDEPENDENT_SIGNALS]

    return _HypothesisMatch(
        hypothesis=IntentHypothesis.PAYEE_REDIRECTION,
        confidence=confidence,
        basis=basis,
        signal_codes=frozenset(
            {
                IntentSignalCode.PAYEE_ADD_THEN_PAYOUT,
                IntentSignalCode.NEW_PAYEE,
                IntentSignalCode.LARGE_PAYOUT,
                IntentSignalCode.EVENT_PAYEE_REGISTRATION,
                IntentSignalCode.EVENT_PAYOUT,
            }
        ),
    )


def _velocity_match(signals: IntentSignals) -> _HypothesisMatch | None:
    if not (signals.has_payee_registration_velocity or signals.has_payout_velocity):
        return None

    if signals.has_payee_registration_velocity and signals.has_payout_velocity:
        confidence = IntentConfidence.HIGH
        basis = [ConfidenceReason.TWO_INDEPENDENT_SIGNALS]
    else:
        confidence = IntentConfidence.MEDIUM
        basis = [ConfidenceReason.SINGLE_WEAK_SIGNAL]

    return _HypothesisMatch(
        hypothesis=IntentHypothesis.VELOCITY_ABUSE,
        confidence=confidence,
        basis=basis,
        signal_codes=frozenset(
            {
                IntentSignalCode.PAYEE_REGISTRATION_VELOCITY,
                IntentSignalCode.PAYOUT_VELOCITY,
                IntentSignalCode.EVENT_PAYEE_REGISTRATION,
                IntentSignalCode.EVENT_PAYOUT,
            }
        ),
    )


def _routine_match(signals: IntentSignals) -> _HypothesisMatch | None:
    suspicious = any(
        (
            signals.has_new_device,
            signals.has_new_location,
            signals.has_unusual_time,
            signals.has_new_payee,
            signals.has_large_payout,
            signals.has_payee_add_then_payout,
            signals.has_payee_registration_velocity,
            signals.has_payout_velocity,
            signals.has_canary_interaction,
            signals.has_decoy_routing,
            signals.blocked_payout_count > 0,
            signals.security_anomaly_count > 0,
            signals.mfa_event_count > 0,
            signals.session_revoked,
        )
    )
    if not (signals.baseline_ready and signals.has_payout_activity and not suspicious):
        return None

    return _HypothesisMatch(
        hypothesis=IntentHypothesis.ROUTINE_PAYMENT_OPERATION,
        confidence=IntentConfidence.LOW,
        basis=[
            ConfidenceReason.BASELINE_MATURE,
            ConfidenceReason.ABSENCE_OF_ANOMALY_IS_NOT_PROOF,
        ],
        signal_codes=frozenset({IntentSignalCode.BASELINE_MATURE, IntentSignalCode.EVENT_PAYOUT}),
    )


def _dedupe_refs(
    references: list[IntentEvidenceReference],
) -> list[IntentEvidenceReference]:
    seen: set[tuple[str, str]] = set()
    result: list[IntentEvidenceReference] = []
    for reference in references:
        key = (reference.source.value, reference.ref_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(reference)
    return result


def _fallback_reference(
    signals: IntentSignals, hypothesis: IntentHypothesis
) -> IntentEvidenceReference:
    if hypothesis is IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE:
        summary = "No supported evidence was sufficient to form an intent hypothesis."
    elif hypothesis is IntentHypothesis.ROUTINE_PAYMENT_OPERATION:
        summary = "The session had a mature baseline and no supported anomaly signal."
    else:
        summary = "The hypothesis was derived from the session's structured signal set."
    return IntentEvidenceReference(
        source=IntentEvidenceSource.SESSION,
        ref_id=str(signals.session_id),
        summary=summary,
        occurred_at=signals.last_event_at,
    )


def _evidence_for(
    signals: IntentSignals,
    matches: list[_HypothesisMatch],
) -> list[IntentEvidenceReference]:
    wanted: set[IntentSignalCode] = set()
    for match in matches:
        wanted.update(match.signal_codes)
    references = [
        reference
        for reference in signals.evidence
        if set(reference.signal_codes).intersection(wanted)
    ]
    if not references:
        references = [_fallback_reference(signals, match.hypothesis) for match in matches[:1]]
    return _dedupe_refs(references)[:12]


def _limitations(signals: IntentSignals) -> list[str]:
    limitations = list(_BASE_LIMITATIONS)
    if signals.baseline_provisional:
        limitations.append(
            "The behavioural baseline is provisional, so device, location, time and payee "
            "novelty cannot establish an intent hypothesis."
        )
    if signals.unknown_event_count:
        limitations.append("Unrecognized event types were counted but not interpreted.")
    if signals.hour_baseline_ready is False:
        limitations.append(
            "No usable hour-of-day baseline was available, so unusual-time intent was not inferred."
        )
    return limitations


def _unknown_analysis(signals: IntentSignals) -> IntentAnalysis:
    basis = [ConfidenceReason.NO_SUPPORTING_EVIDENCE]
    if signals.baseline_provisional:
        basis.append(ConfidenceReason.BASELINE_PROVISIONAL)
    if signals.event_count == 0 and not signals.has_payout_activity:
        abstention_reason = "No supported events or payout records were available for this session."
    elif signals.baseline_provisional:
        abstention_reason = (
            "The behavioural baseline is provisional, so novelty cannot support an intent "
            "hypothesis."
        )
    else:
        abstention_reason = (
            "No supported deterministic rule had enough independent evidence to form an "
            "intent hypothesis."
        )
    wanted = {
        IntentSignalCode.BASELINE_PROVISIONAL,
        IntentSignalCode.NO_EVENTS,
    }
    evidence = [
        reference
        for reference in signals.evidence
        if set(reference.signal_codes).intersection(wanted)
    ]
    if not evidence:
        evidence = [_fallback_reference(signals, IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE)]
    return IntentAnalysis(
        primary_intent=IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE,
        secondary_intents=[],
        confidence=IntentConfidence.UNKNOWN,
        confidence_basis=basis,
        evidence=_dedupe_refs(evidence)[:12],
        limitations=_limitations(signals),
        abstention_reason=abstention_reason,
        signals=signals,
        classifier_version=_CLASSIFIER_VERSION,
    )


def classify_intent(signals: IntentSignals) -> IntentAnalysis:
    """Classify a signal set into at most one primary and two secondary hypotheses."""
    matches = [
        match
        for match in (
            _containment_match(signals),
            _takeover_match(signals),
            _payee_redirection_match(signals),
            _velocity_match(signals),
            _routine_match(signals),
        )
        if match is not None
    ]
    if not matches:
        return _unknown_analysis(signals)

    primary = matches[0]
    secondary = [match.hypothesis for match in matches[1:3]]
    selected = matches[:3]
    return IntentAnalysis(
        primary_intent=primary.hypothesis,
        secondary_intents=secondary,
        confidence=primary.confidence,
        confidence_basis=primary.basis,
        evidence=_evidence_for(signals, selected),
        limitations=_limitations(signals),
        signals=signals,
        classifier_version=_CLASSIFIER_VERSION,
    )
