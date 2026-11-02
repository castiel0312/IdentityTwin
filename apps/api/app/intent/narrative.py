"""Deterministic narrative and redacted LLM projection for intent profiles.

The LLM may rewrite prose only. The classifier result is built first, persisted
with the profile, and the projection below deliberately excludes hashes, raw
identifiers, arbitrary metadata and prior narrative text.
"""

from dataclasses import dataclass
from typing import Any

from app.intent.taxonomy import IntentConfidence, IntentHypothesis
from app.schemas.intent import IntentAnalysis, IntentNarrative

_LABELS = {
    IntentHypothesis.CONTAINMENT_PROBING: "containment probing",
    IntentHypothesis.ACCOUNT_TAKEOVER: "account takeover",
    IntentHypothesis.PAYEE_REDIRECTION: "payee redirection",
    IntentHypothesis.VELOCITY_ABUSE: "payment velocity abuse",
    IntentHypothesis.ROUTINE_PAYMENT_OPERATION: "routine payment operation",
    IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE: "undetermined intent",
}

_SIGNAL_KEYS = (
    "event_count",
    "unknown_event_count",
    "auth_event_count",
    "mfa_event_count",
    "security_anomaly_count",
    "pageview_count",
    "heartbeat_count",
    "payee_registration_count",
    "payout_event_count",
    "has_new_device",
    "has_new_location",
    "has_unusual_time",
    "has_new_payee",
    "has_large_payout",
    "has_payee_add_then_payout",
    "has_payee_registration_velocity",
    "has_payout_velocity",
    "has_canary_interaction",
    "has_decoy_routing",
    "blocked_payout_count",
    "session_trust_level",
    "session_status",
    "session_risk_score",
    "session_revoked",
    "baseline_ready",
    "baseline_provisional",
    "hour_baseline_ready",
    "has_payout_activity",
    "max_payee_registrations_in_window",
    "max_payouts_in_window",
)

_TOP_LEVEL_KEYS = frozenset(
    {
        "session_id",
        "primary_intent",
        "secondary_intents",
        "confidence",
        "confidence_basis",
        "abstention_reason",
        "evidence",
        "limitations",
        "signals",
    }
)
_EVIDENCE_KEYS = frozenset({"source", "ref_id", "summary", "occurred_at", "signal_codes"})
_FORBIDDEN_KEYS = frozenset(
    {
        "device_id",
        "device_fingerprint",
        "ip_address",
        "recipient",
        "recipient_email",
        "reference_note",
        "metadata",
        "metadata_payload",
        "title",
        "description",
        "trigger_meta",
        "secret_value",
        "tag",
        "provider_payload",
        "provider_reference",
        "evidence_summary",
        "notes",
        "narrative",
        "sender_item_id",
    }
)


@dataclass(frozen=True)
class IntentLlmProjection:
    payload: dict[str, Any]
    redaction_applied: bool


def compact_analysis(analysis: IntentAnalysis) -> IntentAnalysis:
    """Remove the raw signal evidence list before persistence.

    ``analysis.evidence`` remains the bounded, classifier-selected reference set.
    The full signal evidence is an internal extraction detail and does not need
    to be stored twice in every snapshot.
    """

    signals = analysis.signals.model_copy(update={"evidence": []})
    return analysis.model_copy(update={"signals": signals})


def _confidence_text(confidence: IntentConfidence) -> str:
    if confidence is IntentConfidence.UNKNOWN:
        return "no confidence band can be assigned"
    return f"{confidence.value.lower()} ordinal confidence"


def deterministic_narrative(analysis: IntentAnalysis) -> IntentNarrative:
    label = _LABELS.get(analysis.primary_intent, "an advisory intent")
    if analysis.primary_intent is IntentHypothesis.UNKNOWN_INSUFFICIENT_EVIDENCE:
        headline = "Intent remains undetermined from the current evidence"
    else:
        headline = f"Advisory hypothesis: {label.title()}"

    basis = (
        ", ".join(reason.value.lower().replace("_", " ") for reason in analysis.confidence_basis)
        or "no specific confidence reason was recorded"
    )
    secondary = (
        ", ".join(_LABELS.get(item, item.value).title() for item in analysis.secondary_intents)
        or "none"
    )
    summary = (
        f"The deterministic classifier selected {analysis.primary_intent.value} with "
        f"{_confidence_text(analysis.confidence)}. Secondary hypotheses considered: "
        f"{secondary}. Basis: {basis}. The profile cites "
        f"{len(analysis.evidence)} bounded evidence reference(s) from the "
        "authenticated merchant and session scope. This is a provisional advisory "
        "hypothesis, not proof of intent, and it does not change enforcement."
    )
    if analysis.abstention_reason:
        summary = f"{summary} Abstention note: {analysis.abstention_reason}"

    notes = list(analysis.limitations)
    if not notes:
        notes = [
            "The profile is advisory and never changes risk scoring, routing or payment execution."
        ]
    return IntentNarrative(
        headline=headline[:200],
        summary=summary[:1600],
        uncertainty_notes=notes[:12],
        generated_by="deterministic",
    )


def build_intent_llm_projection(analysis: IntentAnalysis) -> IntentLlmProjection:
    signals = analysis.signals.model_dump(mode="json")
    payload = {
        "session_id": str(analysis.signals.session_id),
        "primary_intent": analysis.primary_intent.value,
        "secondary_intents": [item.value for item in analysis.secondary_intents],
        "confidence": analysis.confidence.value,
        "confidence_basis": [item.value for item in analysis.confidence_basis],
        "abstention_reason": analysis.abstention_reason,
        "evidence": [reference.model_dump(mode="json") for reference in analysis.evidence],
        "limitations": list(analysis.limitations),
        "signals": {key: signals[key] for key in _SIGNAL_KEYS if key in signals},
    }
    return IntentLlmProjection(
        payload=payload,
        redaction_applied=_verify_projection(payload),
    )


def _has_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                return True
            if _has_forbidden_key(nested):
                return True
    elif isinstance(value, list):
        return any(_has_forbidden_key(item) for item in value)
    return False


def _verify_projection(payload: dict[str, Any]) -> bool:
    if set(payload) - _TOP_LEVEL_KEYS:
        return False
    if _has_forbidden_key(payload):
        return False
    evidence = payload.get("evidence")
    if not isinstance(evidence, list):
        return False
    if any(not isinstance(item, dict) or set(item) - _EVIDENCE_KEYS for item in evidence):
        return False
    signals = payload.get("signals")
    if not isinstance(signals, dict) or set(signals) - set(_SIGNAL_KEYS):
        return False
    return True
