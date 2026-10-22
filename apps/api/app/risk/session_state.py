"""Session risk ledger helpers: deduplication, latching and behavioural decay.

The ledger is the single source of truth for how a session score was built.
Every score change is expressed as an explicit contribution so that the score
can always be re-derived from auditable evidence.
"""

import hashlib
from datetime import datetime

from app.risk.config import RiskConfig
from app.risk.schemas import FeatureVector, RiskEvaluationRequest, SessionRiskState

# Signals that may only fire once per session.
SESSION_LATCHED_SIGNALS: frozenset[str] = frozenset(
    {"NEW_DEVICE", "NEW_LOCATION", "UNUSUAL_TIME", "CANARY_INTERACTION"}
)


def event_fingerprint(
    session_id: object,
    request: RiskEvaluationRequest,
    features: FeatureVector,
) -> str:
    """Build a stable fingerprint used to detect replayed events."""
    occurred = request.occurred_at.isoformat() if request.occurred_at else ""
    raw = "|".join(
        [
            str(session_id),
            features.event_type,
            features.action_type,
            occurred,
            f"{features.amount:.4f}",
            features.recipient_hash or "",
        ]
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def is_duplicate_event(state: SessionRiskState, fingerprint: str) -> bool:
    return fingerprint in state.event_fingerprints


def remember_event(state: SessionRiskState, fingerprint: str, config: RiskConfig) -> None:
    state.event_fingerprints.append(fingerprint)
    if len(state.event_fingerprints) > config.max_event_fingerprints:
        state.event_fingerprints = state.event_fingerprints[-config.max_event_fingerprints :]


def is_latched(state: SessionRiskState, signal: str) -> bool:
    return signal in state.latched_signals


def has_session_anomalies(state: SessionRiskState) -> bool:
    """True while the session still holds session scoped anomaly evidence.

    Session scoped evidence (new device, new location, unusual hour, canary)
    marks the whole session as compromised and therefore blocks behavioural
    decay. Only transient per event evidence may fade.
    """
    return any(signal in state.latched_signals for signal in SESSION_LATCHED_SIGNALS)


def latch(state: SessionRiskState, signal: str) -> bool:
    """Latch a session scoped signal. Returns True when it was newly latched."""
    if signal in state.latched_signals:
        return False
    state.latched_signals.append(signal)
    return True


def is_payee_latched(state: SessionRiskState, recipient_hash: str | None) -> bool:
    return bool(recipient_hash) and recipient_hash in state.fired_payees


def latch_payee(state: SessionRiskState, recipient_hash: str | None) -> bool:
    if not recipient_hash:
        return False
    if recipient_hash in state.fired_payees:
        return False
    state.fired_payees.append(recipient_hash)
    return True


def decayable_points(state: SessionRiskState) -> float:
    """Points that behavioural decay is still allowed to remove.

    Canary evidence is permanent and is never decayed.
    """
    return max(0.0, state.raw_points_sum - state.canary_points - state.decay_points_total)


def apply_decay(state: SessionRiskState, requested: float, config: RiskConfig) -> float:
    """Remove up to ``requested`` transient points from the session score."""
    if requested <= 0:
        return 0.0
    removable = min(requested, decayable_points(state))
    if removable <= 0:
        return 0.0
    state.decay_points_total += removable
    state.current_score = max(0.0, state.current_score - removable)
    return removable


def is_protected_action(action_type: str, amount: float, config: RiskConfig) -> bool:
    """Protected actions never receive behavioural decay."""
    if amount > 0:
        return True
    return (action_type or "").strip().lower() in config.protected_actions


def prune_contributions(state: SessionRiskState, limit: int = 500) -> None:
    """Bound the stored ledger while keeping the authoritative totals intact."""
    if len(state.contributions) > limit:
        state.contributions = state.contributions[-limit:]


def touch(state: SessionRiskState, now: datetime) -> None:
    state.updated_at = now
