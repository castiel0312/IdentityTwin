"""Cross-event attack sequence detection.

Sequences describe behaviour that only becomes malicious when two or more
events are correlated in time, for example registering a brand new payee and
immediately paying it a large amount.
"""

from datetime import datetime, timedelta

from app.risk.schemas import FeatureVector, SequenceMarker, SessionRiskState

SEQUENCE_PAYEE_ADD_THEN_PAYOUT = "payee_add_then_payout"
SEQUENCE_PAYEE_ADDED = "payee.added"


def register_payee_registration(
    state: SessionRiskState,
    recipient_hash: str | None,
    occurred_at: datetime,
    marker_id: str,
) -> SequenceMarker | None:
    """Record that a payee registration happened inside this session."""
    if not recipient_hash:
        return None
    marker = SequenceMarker(
        marker_id=marker_id,
        sequence_type=SEQUENCE_PAYEE_ADDED,
        recipient_hash=recipient_hash,
        occurred_at=occurred_at,
    )
    state.sequence_markers.append(marker)
    if recipient_hash not in state.registered_payees:
        state.registered_payees.append(recipient_hash)
    return marker


def detect_payee_add_then_payout(
    state: SessionRiskState,
    features: FeatureVector,
    occurred_at: datetime,
    window_seconds: int,
) -> SequenceMarker | None:
    """Detect a payout that follows a payee registration for the same payee.

    Each registration can only trigger the sequence once, so repeated payouts
    to the same freshly registered payee do not stack unbounded points.
    """
    if not features.recipient_hash:
        return None

    consumed = set(state.consumed_markers)
    window_start = occurred_at - timedelta(seconds=window_seconds)

    candidates = [
        marker
        for marker in state.sequence_markers
        if marker.sequence_type == SEQUENCE_PAYEE_ADDED
        and marker.recipient_hash == features.recipient_hash
        and marker.marker_id not in consumed
        and window_start <= marker.occurred_at <= occurred_at
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda marker: marker.occurred_at)
