"""Deterministic risk scoring.

The scorer is a pure function of the extracted features, the session ledger and
the resolved configuration. It never mutates global state and never consults a
random source, which makes every score reproducible and auditable.
"""

from dataclasses import dataclass, field
from datetime import datetime

from app.risk.config import RiskConfig
from app.risk.schemas import (
    FeatureVector,
    RiskContribution,
    RiskEvaluationRequest,
    SequenceMarker,
    SessionRiskState,
)
from app.risk.session_state import (
    apply_decay,
    has_session_anomalies,
    is_latched,
    is_payee_latched,
    is_protected_action,
    latch,
    latch_payee,
)
from app.schemas.sessions import TrustLevel

SIGNAL_NEW_DEVICE = "NEW_DEVICE"
SIGNAL_NEW_LOCATION = "NEW_LOCATION"
SIGNAL_UNUSUAL_TIME = "UNUSUAL_TIME"
SIGNAL_NEW_PAYEE = "NEW_PAYEE"
SIGNAL_LARGE_PAYOUT = "LARGE_PAYOUT"
SIGNAL_NEW_PAYEE_LARGE_PAYOUT = "NEW_PAYEE_LARGE_PAYOUT"
SIGNAL_PAYEE_ADD_THEN_PAYOUT = "PAYEE_ADD_THEN_PAYOUT"
SIGNAL_CANARY_INTERACTION = "CANARY_INTERACTION"

REASON_NEW_DEVICE = "NEW_DEVICE_DETECTED"
REASON_NEW_LOCATION = "NEW_LOCATION_DETECTED"
REASON_UNUSUAL_TIME = "UNUSUAL_TRANSACTION_TIME"
REASON_NEW_PAYEE = "NEW_PAYEE_DESTINATION"
REASON_LARGE_PAYOUT = "LARGE_PAYOUT_THRESHOLD_EXCEEDED"
REASON_COMPOUND = "COMPOUND_NEW_PAYEE_AND_LARGE_PAYOUT"
REASON_SEQUENCE = "PAYEE_ADD_THEN_PAYOUT_SEQUENCE"
REASON_CANARY = "CANARY_INTERACTION_LEVEL_3_OVERRIDE"
REASON_BASELINE = "BASELINE_NORMAL_OPERATION"
REASON_DECAY = "RISK_DECAY_APPLIED"
REASON_DUPLICATE = "DUPLICATE_EVENT_IGNORED"

# Newness signals are attenuated while the identity twin is still provisional.
_PROVISIONAL_SIGNALS = frozenset({SIGNAL_NEW_DEVICE, SIGNAL_NEW_LOCATION, SIGNAL_NEW_PAYEE})


@dataclass
class ScoringOutcome:
    """Result of a single scoring pass."""

    score: float
    level: TrustLevel
    risk_signals: dict[str, float] = field(default_factory=dict)
    reason_codes: list[str] = field(default_factory=list)
    contributions: list[RiskContribution] = field(default_factory=list)
    raw_points_sum: float = 0.0
    decay_points: float = 0.0
    canary: bool = False


def _weight_for(signal: str, config: RiskConfig, provisional: bool) -> float:
    base = {
        SIGNAL_NEW_DEVICE: config.weight_new_device,
        SIGNAL_NEW_LOCATION: config.weight_new_location,
        SIGNAL_UNUSUAL_TIME: config.weight_unusual_time,
        SIGNAL_NEW_PAYEE: config.weight_new_payee,
        SIGNAL_LARGE_PAYOUT: config.weight_large_payout,
        SIGNAL_NEW_PAYEE_LARGE_PAYOUT: config.weight_new_payee_large_payout,
        SIGNAL_PAYEE_ADD_THEN_PAYOUT: config.weight_payee_add_then_payout,
        SIGNAL_CANARY_INTERACTION: config.weight_canary_interaction,
    }[signal]
    if provisional and signal in _PROVISIONAL_SIGNALS:
        return round(base * config.provisional_factor, 4)
    return base


def score_event(
    *,
    request: RiskEvaluationRequest,
    features: FeatureVector,
    state: SessionRiskState,
    config: RiskConfig,
    canary: bool,
    session_score: float,
    now: datetime,
    open_incident: bool = False,
    session_active: bool = True,
    sequence_marker: SequenceMarker | None = None,
    event_id: str | None = None,
) -> ScoringOutcome:
    """Score a single event and update the session ledger accordingly."""
    contributions: list[RiskContribution] = []
    reason_codes: list[str] = []
    provisional = features.twin_provisional
    occurred_at = request.occurred_at or now

    def add_signal(
        name: str,
        reason: str,
        points: float,
        latch_key: str | None = None,
        detail: dict | None = None,
    ) -> None:
        contributions.append(
            RiskContribution(
                name=name,
                points=round(points, 4),
                reason_code=reason,
                kind="signal",
                event_id=event_id,
                occurred_at=occurred_at,
                latch_key=latch_key,
                detail=detail or {},
            )
        )
        reason_codes.append(reason)

    # 1. Inherit the authoritative session score. A score that was raised
    #    outside of the engine (for example by a manual isolation) is carried
    #    forward as an explicit contribution.
    base = max(state.current_score, session_score)
    if session_score > state.current_score:
        delta = session_score - state.current_score
        state.carried_forward += delta
        contributions.append(
            RiskContribution(
                name="SESSION_CARRIED_FORWARD",
                points=round(delta, 4),
                reason_code="SESSION_SCORE_CARRIED_FORWARD",
                kind="carry_forward",
                event_id=event_id,
                occurred_at=occurred_at,
                detail={"session_score": session_score, "ledger_score": state.current_score},
            )
        )

    new_payee_fired = False

    # 2. Session scoped newness signals (latched once per session).
    if features.is_new_device and not is_latched(state, SIGNAL_NEW_DEVICE):
        add_signal(
            SIGNAL_NEW_DEVICE,
            REASON_NEW_DEVICE,
            _weight_for(SIGNAL_NEW_DEVICE, config, provisional),
            latch_key=SIGNAL_NEW_DEVICE,
        )
        latch(state, SIGNAL_NEW_DEVICE)

    if features.is_new_location and not is_latched(state, SIGNAL_NEW_LOCATION):
        add_signal(
            SIGNAL_NEW_LOCATION,
            REASON_NEW_LOCATION,
            _weight_for(SIGNAL_NEW_LOCATION, config, provisional),
            latch_key=SIGNAL_NEW_LOCATION,
        )
        latch(state, SIGNAL_NEW_LOCATION)

    if features.is_unusual_hour and not is_latched(state, SIGNAL_UNUSUAL_TIME):
        add_signal(
            SIGNAL_UNUSUAL_TIME,
            REASON_UNUSUAL_TIME,
            _weight_for(SIGNAL_UNUSUAL_TIME, config, provisional),
            latch_key=SIGNAL_UNUSUAL_TIME,
        )
        latch(state, SIGNAL_UNUSUAL_TIME)

    # 3. Per event payee and payout signals.
    if features.is_new_payee and not is_payee_latched(state, features.recipient_hash):
        add_signal(
            SIGNAL_NEW_PAYEE,
            REASON_NEW_PAYEE,
            _weight_for(SIGNAL_NEW_PAYEE, config, provisional),
            latch_key=features.recipient_hash,
            detail={"recipient_hash": features.recipient_hash},
        )
        latch_payee(state, features.recipient_hash)
        new_payee_fired = True

    if features.is_large_payout:
        add_signal(
            SIGNAL_LARGE_PAYOUT,
            REASON_LARGE_PAYOUT,
            _weight_for(SIGNAL_LARGE_PAYOUT, config, provisional),
        )

    if new_payee_fired and features.is_large_payout:
        add_signal(
            SIGNAL_NEW_PAYEE_LARGE_PAYOUT,
            REASON_COMPOUND,
            _weight_for(SIGNAL_NEW_PAYEE_LARGE_PAYOUT, config, provisional),
        )

    if sequence_marker is not None:
        add_signal(
            SIGNAL_PAYEE_ADD_THEN_PAYOUT,
            REASON_SEQUENCE,
            _weight_for(SIGNAL_PAYEE_ADD_THEN_PAYOUT, config, provisional),
            detail={
                "sequence_type": sequence_marker.sequence_type,
                "marker_id": sequence_marker.marker_id,
            },
        )

    # 4. Canary interaction is permanent evidence and forces level 3.
    if canary and not is_latched(state, SIGNAL_CANARY_INTERACTION):
        add_signal(
            SIGNAL_CANARY_INTERACTION,
            REASON_CANARY,
            _weight_for(SIGNAL_CANARY_INTERACTION, config, provisional),
            latch_key=SIGNAL_CANARY_INTERACTION,
        )
        latch(state, SIGNAL_CANARY_INTERACTION)
        state.canary_seen = True

    signal_points = sum(c.points for c in contributions if c.kind == "signal")
    state.raw_points_sum = round(state.raw_points_sum + signal_points, 4)
    if canary:
        state.canary_points = round(
            state.canary_points
            + sum(
                c.points
                for c in contributions
                if c.kind == "signal" and c.name == SIGNAL_CANARY_INTERACTION
            ),
            4,
        )

    state.current_score = round(base + signal_points, 4)

    # 5. Behavioural decay only applies to clean, unprotected activity.
    #    Sessions that still carry session scoped anomaly evidence (a new
    #    device, a new location, an unusual hour or a canary hit) keep their
    #    score, so a heartbeat event can never erase the evidence of a
    #    compromised session.
    decay_points = 0.0
    decay_eligible = (
        signal_points == 0
        and not canary
        and not open_incident
        and session_active
        and not has_session_anomalies(state)
        and not is_protected_action(features.action_type, features.amount, config)
    )
    if decay_eligible:
        decay_points = apply_decay(state, config.decay_points_per_event, config)
        if decay_points > 0:
            contributions.append(
                RiskContribution(
                    name="RISK_DECAY",
                    points=-round(decay_points, 4),
                    reason_code=REASON_DECAY,
                    kind="decay",
                    event_id=event_id,
                    occurred_at=occurred_at,
                    detail={"decay_points": decay_points},
                )
            )
            reason_codes.append(REASON_DECAY)

    score = round(max(0.0, min(100.0, state.current_score)), 4)

    # 6. A canary forces isolation. The isolation floor is an explicit
    #    contribution so the ledger always explains the final score.
    if canary:
        floor = max(0.0, round(config.threshold_isolated - score, 4))
        if floor > 0:
            contributions.append(
                RiskContribution(
                    name="CANARY_ISOLATION_FLOOR",
                    points=floor,
                    reason_code="CANARY_ISOLATION_FLOOR_APPLIED",
                    kind="isolation_floor",
                    event_id=event_id,
                    occurred_at=occurred_at,
                    detail={"threshold": config.threshold_isolated},
                )
            )
            score = round(min(100.0, score + floor), 4)
            state.current_score = score

    # 7. Trust level resolution.
    if canary:
        level = TrustLevel.ISOLATED
    elif score >= config.threshold_isolated:
        level = TrustLevel.ISOLATED
        reason_codes.append("SESSION_ISOLATION_THRESHOLD_REACHED")
    elif score >= config.threshold_decoy:
        level = TrustLevel.DECOY
        reason_codes.append("DECOY_HONEY_ROUTING_THRESHOLD_REACHED")
    elif score >= config.threshold_restricted:
        level = TrustLevel.RESTRICTED
        reason_codes.append("RESTRICTED_STEP_UP_THRESHOLD_REACHED")
    else:
        level = TrustLevel.NORMAL
        reason_codes.append("NORMAL_TRUST_ELIGIBLE")

    risk_signals = {c.name: c.points for c in contributions if c.kind == "signal"}
    if not risk_signals:
        risk_signals = {"BASELINE_ACTIVITY": 0.0}
        reason_codes.append(REASON_BASELINE)

    return ScoringOutcome(
        score=score,
        level=level,
        risk_signals=risk_signals,
        reason_codes=reason_codes,
        contributions=contributions,
        raw_points_sum=round(signal_points, 4),
        decay_points=round(decay_points, 4),
        canary=canary,
    )
