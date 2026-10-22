"""Pure orchestration of the behavioral twin risk engine.

The engine evaluates a single event against an identity twin baseline and a
session ledger. It performs no I/O: the database aware adapter in
``app.risk.service`` loads and persists the twin and ledger around this core.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.risk.canary import CanaryRegistry, InMemoryCanaryRegistry, detect_canary
from app.risk.config import RiskConfig, get_risk_config
from app.risk.features import extract_features
from app.risk.schemas import (
    RiskEvaluationRequest,
    RiskEvaluationResult,
    SessionRiskState,
    TwinSnapshot,
)
from app.risk.scorer import (
    REASON_DUPLICATE,
    ScoringOutcome,
    score_event,
)
from app.risk.sequences import (
    detect_payee_add_then_payout,
    register_payee_registration,
)
from app.risk.session_state import (
    event_fingerprint,
    is_duplicate_event,
    prune_contributions,
    remember_event,
    touch,
)
from app.risk.twin import (
    apply_amount_observation,
    apply_context_observations,
    apply_observation,
)
from app.schemas.sessions import TrustLevel


@dataclass
class EngineOutcome:
    """Everything the persistence layer needs after one evaluation."""

    result: RiskEvaluationResult
    twin: TwinSnapshot
    state: SessionRiskState
    twin_updated: bool = False


def _level_for(score: float, config: RiskConfig) -> TrustLevel:
    if score >= config.threshold_isolated:
        return TrustLevel.ISOLATED
    if score >= config.threshold_decoy:
        return TrustLevel.DECOY
    if score >= config.threshold_restricted:
        return TrustLevel.RESTRICTED
    return TrustLevel.NORMAL


class BehavioralTwinEngine:
    """Deterministic, database independent behavioral twin risk engine."""

    def __init__(
        self,
        config: RiskConfig | None = None,
        registry: CanaryRegistry | None = None,
    ) -> None:
        self.config = config or get_risk_config()
        self.registry = registry or InMemoryCanaryRegistry(self.config.canary_identifiers)

    def evaluate(
        self,
        request: RiskEvaluationRequest,
        twin: TwinSnapshot,
        state: SessionRiskState,
        *,
        session_score: float = 0.0,
        now: datetime | None = None,
        open_incident: bool = False,
        session_active: bool = True,
    ) -> EngineOutcome:
        moment = now or datetime.now(timezone.utc)
        config = self.config

        canary = detect_canary(request, self.registry)
        features = extract_features(request, twin, state, config, moment)
        fingerprint = event_fingerprint(request.session_id, request, features)

        if is_duplicate_event(state, fingerprint):
            level = _level_for(state.current_score, config)
            reason_codes = [REASON_DUPLICATE]
            if level == TrustLevel.ISOLATED:
                reason_codes.append("SESSION_ISOLATION_THRESHOLD_REACHED")
            elif level == TrustLevel.DECOY:
                reason_codes.append("DECOY_HONEY_ROUTING_THRESHOLD_REACHED")
            elif level == TrustLevel.RESTRICTED:
                reason_codes.append("RESTRICTED_STEP_UP_THRESHOLD_REACHED")
            else:
                reason_codes.append("NORMAL_TRUST_ELIGIBLE")
            result = RiskEvaluationResult(
                session_id=request.session_id,
                risk_score=round(max(0.0, min(100.0, state.current_score)), 4),
                evaluated_trust_level=level,
                risk_signals={"BASELINE_ACTIVITY": 0.0},
                reason_codes=reason_codes,
                evaluated_at=moment,
                contributions=[],
                features=features,
                twin_provisional=features.twin_provisional,
                twin_sample_count=features.twin_sample_count,
                raw_points_sum=0.0,
                decay_points=0.0,
                session_carried_forward=state.carried_forward,
                duplicate_event=True,
                twin_updated=False,
            )
            return EngineOutcome(result=result, twin=twin, state=state, twin_updated=False)

        # Sequence tracking: a payee registration is remembered so that a
        # payout to the same payee inside the correlation window is detected.
        sequence_marker = None
        if features.is_payee_registration and features.recipient_hash:
            register_payee_registration(
                state=state,
                recipient_hash=features.recipient_hash,
                occurred_at=request.occurred_at or moment,
                marker_id=fingerprint[:16],
            )
        else:
            sequence_marker = detect_payee_add_then_payout(
                state=state,
                features=features,
                occurred_at=request.occurred_at or moment,
                window_seconds=config.sequence_window_seconds,
            )
            if (
                sequence_marker is not None
                and sequence_marker.marker_id not in state.consumed_markers
            ):
                state.consumed_markers.append(sequence_marker.marker_id)

        outcome: ScoringOutcome = score_event(
            request=request,
            features=features,
            state=state,
            config=config,
            canary=canary,
            session_score=session_score,
            now=moment,
            open_incident=open_incident,
            session_active=session_active,
            sequence_marker=sequence_marker,
            event_id=str(request.event_id) if request.event_id else None,
        )

        remember_event(state, fingerprint, config)

        # Twin learning policy. The twin is only taught by clean, settled
        # activity. Anomalous events never contaminate the baseline.
        #
        # The decision uses the extracted features rather than the emitted
        # contributions only: a session scoped signal is latched after the
        # first occurrence, so a later event in the same session would look
        # clean while still introducing a device that the twin has never
        # seen. Comparing against the twin prevents that contamination.
        #
        # The hour-of-day signal is deliberately not a learning blocker: the
        # hour histogram is part of the baseline, so an hour that the
        # identity has not used yet has to be learnable, otherwise the
        # baseline could never grow beyond the very first hours.
        updated_twin = twin
        twin_updated = False
        signal_names = {c.name for c in outcome.contributions if c.kind == "signal"}
        blocking_signals = signal_names - {"UNUSUAL_TIME", "PAYEE_ADD_THEN_PAYOUT"}
        introduces_nowness = (
            features.is_new_device or features.is_new_location or features.is_new_payee
        )
        learnable = (
            session_active
            and not canary
            and not open_incident
            and outcome.level == TrustLevel.NORMAL
            and (
                (
                    features.twin_provisional
                    and blocking_signals.issubset({"NEW_DEVICE", "NEW_LOCATION", "NEW_PAYEE"})
                )
                or (not features.twin_provisional and not introduces_nowness)
            )
        )
        if learnable:
            updated_twin = apply_observation(
                twin=updated_twin, features=features, config=config, now=moment
            )
            updated_twin = apply_amount_observation(
                twin=updated_twin, features=features, config=config, now=moment
            )
            twin_updated = True
        else:
            # The payout size baseline is learned from every event of the
            # established context, even when the event is only unusual in size
            # or in timing. Without it a merchant whose payouts are normally
            # large would stay permanently elevated, and the engine could
            # never tell "large" from "large for this identity". Novelty
            # signals (new device, new location, new payee, a payee-add then
            # payout sequence, a canary hit) never contribute, so a hostile
            # context cannot inflate the baseline.
            hostile_signals = signal_names & {
                "NEW_DEVICE",
                "NEW_LOCATION",
                "NEW_PAYEE",
                "PAYEE_ADD_THEN_PAYOUT",
                "CANARY_INTERACTION",
            }
            amount_learnable = (
                session_active
                and not canary
                and not open_incident
                and not hostile_signals
                and features.amount > 0
            )
            if amount_learnable:
                updated_twin = apply_amount_observation(
                    twin=updated_twin, features=features, config=config, now=moment
                )
                twin_updated = True

        # Context observations (device, location, payee) are counted
        # separately from the full learning. A context item becomes part of
        # the identity baseline once it has been observed often enough, which
        # keeps legitimate context expansion (a second phone, a second
        # office) from being flagged forever.
        #
        # Only events whose sole finding is newness and that keep the session
        # below the action threshold may contribute. A hostile compound event
        # therefore never confirms its own context: the attacker stays an
        # unknown device and an unknown location no matter how often the
        # attacker comes back.
        counter_signals = signal_names - {"NEW_DEVICE", "NEW_LOCATION", "NEW_PAYEE"}
        count_context = (
            session_active
            and not canary
            and not open_incident
            and outcome.level == TrustLevel.NORMAL
            and not counter_signals
        )
        if count_context:
            updated_twin = apply_context_observations(
                twin=updated_twin, features=features, config=config, now=moment
            )
            twin_updated = True

        state.contributions.extend(outcome.contributions)
        prune_contributions(state)
        touch(state, moment)

        result = RiskEvaluationResult(
            session_id=request.session_id,
            risk_score=outcome.score,
            evaluated_trust_level=outcome.level,
            risk_signals=outcome.risk_signals,
            reason_codes=outcome.reason_codes,
            evaluated_at=moment,
            contributions=outcome.contributions,
            features=features,
            twin_provisional=features.twin_provisional,
            twin_sample_count=features.twin_sample_count,
            raw_points_sum=outcome.raw_points_sum,
            decay_points=outcome.decay_points,
            session_carried_forward=state.carried_forward,
            duplicate_event=False,
            twin_updated=twin_updated,
        )

        return EngineOutcome(
            result=result, twin=updated_twin, state=state, twin_updated=twin_updated
        )
