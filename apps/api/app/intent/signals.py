"""Pure intent-signal extraction.

Only structured, derived observations enter this module. It performs no
database access, network access, risk-engine calls or gateway calls. The
future Phase 3 loader is responsible for loading bounded, merchant-scoped
records and for hashing device, location and recipient values before they
reach this module.
"""

from datetime import datetime, timezone

from app.intent.taxonomy import IntentEvidenceSource, IntentSignalCode
from app.risk.timezones import local_hour, resolve_timezone
from app.schemas.intent import (
    EventObservation,
    IntentEvidenceReference,
    IntentExtractionPolicy,
    IntentSignals,
    IntentSourceData,
)

CANONICAL_EVENT_TYPES = frozenset(
    {
        "auth.login",
        "auth.logout",
        "session.heartbeat",
        "behavioral.keystroke",
        "behavioral.mouse",
        "navigation.pageview",
        "payout.attempt",
        "payout.submit",
        "payee.added",
        "security.mfa_challenge",
        "security.anomaly_detected",
    }
)

_EVENT_TYPE_ALIASES = {
    "login": "auth.login",
    "session.login": "auth.login",
    "logout": "auth.logout",
    "session.logout": "auth.logout",
    "pageview": "navigation.pageview",
    "navigation.page_view": "navigation.pageview",
    "payout": "payout.submit",
    "payout.execute": "payout.submit",
    "payout.submitted": "payout.submit",
    "payee_added": "payee.added",
    "payee.add": "payee.added",
    "mfa": "security.mfa_challenge",
    "mfa.challenge": "security.mfa_challenge",
    "anomaly": "security.anomaly_detected",
    "security.anomaly": "security.anomaly_detected",
}

PAYEE_REGISTRATION_ACTIONS = frozenset({"payee.add", "payee.added", "add_payee"})
PAYOUT_ACTIONS = frozenset(
    {"payout", "payout.execute", "payout.submit", "submit_payout", "payout.attempt"}
)
CANARY_ACTIONS = frozenset({"canary.trap", "canary.trigger", "canary_interaction"})
DECOY_STATUSES = frozenset({"decoy_completed", "decoy_forward", "decoy"})
BLOCKED_PAYOUT_STATUSES = frozenset({"blocked", "rejected", "provider_denied"})


def as_utc(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime without consulting wall-clock time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_event_type(value: str | None) -> str:
    """Map known ingestion aliases to canonical event types.

    Unknown values become a private sentinel and are counted only. Raw event
    type text is never included in the derived signal output.
    """
    text = (value or "").strip().lower()
    if text in CANONICAL_EVENT_TYPES:
        return text
    return _EVENT_TYPE_ALIASES.get(text, "unknown")


def normalize_action(value: str | None) -> str:
    """Normalize an action for exact allowlist comparisons."""
    return (value or "").strip().lower()


def is_payee_registration(event_type: str, action: str) -> bool:
    return event_type == "payee.added" or action in PAYEE_REGISTRATION_ACTIONS


def is_payout_event(event_type: str, action: str) -> bool:
    return event_type.startswith("payout.") or action in PAYOUT_ACTIONS


class _EvidenceCollector:
    """Merge signal codes for the same evidence reference without duplicates."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], IntentEvidenceReference] = {}

    def add(
        self,
        source: IntentEvidenceSource,
        ref_id: str,
        summary: str,
        occurred_at: datetime | None,
        codes: list[IntentSignalCode],
    ) -> None:
        key = (source.value, ref_id)
        existing = self._items.get(key)
        if existing is None:
            self._items[key] = IntentEvidenceReference(
                source=source,
                ref_id=ref_id[:128],
                summary=summary[:280],
                occurred_at=occurred_at,
                signal_codes=sorted(set(codes), key=lambda item: item.value),
            )
            return
        merged = sorted(set(existing.signal_codes) | set(codes), key=lambda item: item.value)
        self._items[key] = existing.model_copy(
            update={
                "occurred_at": existing.occurred_at or occurred_at,
                "signal_codes": merged,
            }
        )

    def items(self) -> list[IntentEvidenceReference]:
        return list(self._items.values())


def _known_hashes(observations: dict[str, int], threshold: int) -> set[str]:
    return {value for value, count in observations.items() if count >= threshold}


def _max_events_in_window(
    events: list[EventObservation],
    *,
    window_seconds: int,
) -> tuple[int, list[EventObservation]]:
    """Return the largest event count inside any sliding window and its events."""
    if not events:
        return 0, []
    ordered = sorted(events, key=lambda item: as_utc(item.occurred_at))
    best_start = 0
    best_end = 0
    left = 0
    for right in range(len(ordered)):
        while (
            as_utc(ordered[right].occurred_at) - as_utc(ordered[left].occurred_at)
        ).total_seconds() > window_seconds:
            left += 1
        if right - left > best_end - best_start:
            best_start = left
            best_end = right
    return best_end - best_start + 1, ordered[best_start : best_end + 1]


def _detect_payee_sequence(
    registrations: list[EventObservation],
    payouts: list[EventObservation],
    *,
    window_seconds: int,
) -> tuple[EventObservation, EventObservation] | None:
    ordered_registrations = sorted(registrations, key=lambda item: as_utc(item.occurred_at))
    for payout in sorted(payouts, key=lambda item: as_utc(item.occurred_at)):
        if not payout.recipient_hash:
            continue
        payout_at = as_utc(payout.occurred_at)
        for registration in reversed(ordered_registrations):
            if registration.recipient_hash != payout.recipient_hash:
                continue
            elapsed = (payout_at - as_utc(registration.occurred_at)).total_seconds()
            if 0 <= elapsed <= window_seconds:
                return registration, payout
            if elapsed > window_seconds:
                break
    return None


def _is_unusual_hour(
    event: EventObservation,
    *,
    hour_histogram: dict[str, int],
    hour_total: int,
    hour_concentration: float,
    policy: IntentExtractionPolicy,
    timezone_name: str,
) -> bool:
    if hour_total < policy.min_hour_samples:
        return False
    if hour_concentration < policy.hour_concentration_min:
        return False
    hour = local_hour(as_utc(event.occurred_at), resolve_timezone(timezone_name))
    count = hour_histogram.get(str(hour), 0)
    established = count >= policy.hour_confirm_observations
    active = (count / hour_total) >= policy.active_hour_fraction
    return not established and not active


def extract_intent_signals(
    source: IntentSourceData,
    policy: IntentExtractionPolicy | None = None,
) -> IntentSignals:
    """Extract a bounded signal set from already-loaded structured observations."""
    active_policy = policy or IntentExtractionPolicy()
    evidence = _EvidenceCollector()

    events = sorted(
        source.events,
        key=lambda item: (as_utc(item.occurred_at), as_utc(item.server_received_at)),
    )[-active_policy.max_events :]
    payouts = sorted(source.payouts, key=lambda item: as_utc(item.created_at))[
        -active_policy.max_payouts :
    ]
    canaries = sorted(
        source.canaries,
        key=lambda item: (
            as_utc(item.triggered_at)
            if item.triggered_at
            else datetime.min.replace(tzinfo=timezone.utc)
        ),
    )[-active_policy.max_canaries :]
    incidents = sorted(source.incidents, key=lambda item: as_utc(item.created_at))[
        -active_policy.max_incidents :
    ]

    twin = source.twin
    risk_state = source.risk_state
    baseline_ready = bool(twin and twin.sample_count >= active_policy.min_baseline_samples)
    baseline_provisional = not baseline_ready
    session_status = source.session.status.strip().lower()
    session_trust = source.session.trust_level.strip().upper()

    known_devices = _known_hashes(
        twin.device_observations if twin else {},
        active_policy.context_confirm_observations,
    )
    known_locations = _known_hashes(
        twin.location_observations if twin else {},
        active_policy.context_confirm_observations,
    )
    known_payees = _known_hashes(
        twin.payee_observations if twin else {},
        active_policy.payee_confirm_observations,
    )
    if twin:
        known_devices.update(twin.confirmed_devices)
        known_locations.update(twin.confirmed_locations)

    hour_histogram = twin.hour_histogram if twin else {}
    hour_total = sum(max(0, int(value)) for value in hour_histogram.values())
    hour_concentration = (
        max((max(0, int(value)) for value in hour_histogram.values()), default=0) / hour_total
        if hour_total
        else 0.0
    )
    hour_baseline_ready = bool(baseline_ready and hour_total >= active_policy.min_hour_samples)

    auth_count = 0
    mfa_count = 0
    anomaly_count = 0
    pageview_count = 0
    heartbeat_count = 0
    unknown_event_count = 0
    registration_events: list[EventObservation] = []
    payout_events: list[EventObservation] = []

    has_new_device = False
    has_new_location = False
    has_unusual_time = False
    has_new_payee = False
    has_canary_interaction = False

    for event in events:
        event_type = normalize_event_type(event.event_type)
        action = normalize_action(event.action)
        occurred_at = as_utc(event.occurred_at)

        if event_type == "unknown":
            unknown_event_count += 1
        elif event_type in {"auth.login", "auth.logout"}:
            auth_count += 1
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "Authentication activity was recorded in the session.",
                occurred_at,
                [IntentSignalCode.EVENT_AUTH],
            )
        elif event_type == "security.mfa_challenge":
            mfa_count += 1
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "A step-up or MFA challenge was recorded in the session.",
                occurred_at,
                [IntentSignalCode.EVENT_MFA],
            )
        elif event_type == "security.anomaly_detected":
            anomaly_count += 1
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "A security anomaly event was recorded in the session.",
                occurred_at,
                [IntentSignalCode.EVENT_SECURITY_ANOMALY],
            )
        elif event_type == "navigation.pageview":
            pageview_count += 1
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "Navigation activity was recorded. Page content is not available.",
                occurred_at,
                [IntentSignalCode.EVENT_NAVIGATION],
            )
        elif event_type == "session.heartbeat":
            heartbeat_count += 1
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "Session heartbeat activity was recorded.",
                occurred_at,
                [IntentSignalCode.EVENT_HEARTBEAT],
            )

        if is_payee_registration(event_type, action):
            registration_events.append(event)
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "A payee registration action was recorded in the session.",
                occurred_at,
                [IntentSignalCode.EVENT_PAYEE_REGISTRATION],
            )
        if is_payout_event(event_type, action):
            payout_events.append(event)
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "A payout attempt or submission was recorded in the session.",
                occurred_at,
                [IntentSignalCode.EVENT_PAYOUT],
            )

        if action in CANARY_ACTIONS:
            has_canary_interaction = True
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "An explicit canary interaction marker was recorded.",
                occurred_at,
                [IntentSignalCode.CANARY_INTERACTION],
            )

        if baseline_ready:
            if event.device_hash and event.device_hash not in known_devices:
                if not has_new_device:
                    has_new_device = True
                    evidence.add(
                        IntentEvidenceSource.EVENT,
                        str(event.event_id),
                        "A device outside the established identity baseline was observed.",
                        occurred_at,
                        [IntentSignalCode.NEW_DEVICE],
                    )
                known_devices.add(event.device_hash)
            if event.location_bucket and event.location_bucket not in known_locations:
                if not has_new_location:
                    has_new_location = True
                    evidence.add(
                        IntentEvidenceSource.EVENT,
                        str(event.event_id),
                        "A location bucket outside the established identity baseline was observed.",
                        occurred_at,
                        [IntentSignalCode.NEW_LOCATION],
                    )
                known_locations.add(event.location_bucket)
            if not has_unusual_time and _is_unusual_hour(
                event,
                hour_histogram=hour_histogram,
                hour_total=hour_total,
                hour_concentration=hour_concentration,
                policy=active_policy,
                timezone_name=active_policy.default_timezone,
            ):
                has_unusual_time = True
                evidence.add(
                    IntentEvidenceSource.EVENT,
                    str(event.event_id),
                    "Activity occurred at an hour not established by the identity baseline.",
                    occurred_at,
                    [IntentSignalCode.UNUSUAL_TIME],
                )
            if event.recipient_hash and event.recipient_hash not in known_payees:
                if not has_new_payee:
                    has_new_payee = True
                    evidence.add(
                        IntentEvidenceSource.EVENT,
                        str(event.event_id),
                        "A hashed payee outside the established identity baseline was observed.",
                        occurred_at,
                        [IntentSignalCode.NEW_PAYEE],
                    )
                known_payees.add(event.recipient_hash)

    sequence_pair = _detect_payee_sequence(
        registration_events,
        payout_events,
        window_seconds=active_policy.sequence_window_seconds,
    )
    has_payee_add_then_payout = sequence_pair is not None
    if sequence_pair is not None:
        registration, payout = sequence_pair
        evidence.add(
            IntentEvidenceSource.EVENT,
            str(registration.event_id),
            "A payee registration preceded a payout to the same hashed payee.",
            as_utc(registration.occurred_at),
            [IntentSignalCode.PAYEE_ADD_THEN_PAYOUT],
        )
        evidence.add(
            IntentEvidenceSource.EVENT,
            str(payout.event_id),
            "A payout followed a payee registration for the same hashed payee inside the window.",
            as_utc(payout.occurred_at),
            [IntentSignalCode.PAYEE_ADD_THEN_PAYOUT],
        )

    if risk_state:
        marker_ids = {marker.marker_id for marker in risk_state.sequence_markers}
        consumed_ids = marker_ids.intersection(risk_state.consumed_markers)
        if consumed_ids and not has_payee_add_then_payout:
            has_payee_add_then_payout = True
            marker_id = sorted(consumed_ids)[0]
            evidence.add(
                IntentEvidenceSource.RISK_STATE,
                marker_id,
                "The server-side sequence ledger recorded a consumed payee sequence marker.",
                risk_state.last_evaluated_at,
                [
                    IntentSignalCode.PAYEE_ADD_THEN_PAYOUT,
                    IntentSignalCode.EVENT_PAYOUT,
                ],
            )

    max_registrations, registration_window = _max_events_in_window(
        registration_events,
        window_seconds=active_policy.velocity_window_seconds,
    )
    max_payouts, payout_window = _max_events_in_window(
        payout_events,
        window_seconds=active_policy.velocity_window_seconds,
    )
    has_registration_velocity = max_registrations >= active_policy.velocity_min_registrations
    has_payout_velocity = max_payouts >= active_policy.velocity_min_payouts

    if has_registration_velocity:
        for event in registration_window[: active_policy.velocity_min_registrations]:
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "Payee registrations clustered inside the configured velocity window.",
                as_utc(event.occurred_at),
                [IntentSignalCode.PAYEE_REGISTRATION_VELOCITY],
            )
    if has_payout_velocity:
        for event in payout_window[: active_policy.velocity_min_payouts]:
            evidence.add(
                IntentEvidenceSource.EVENT,
                str(event.event_id),
                "Payout activity clustered inside the configured velocity window.",
                as_utc(event.occurred_at),
                [IntentSignalCode.PAYOUT_VELOCITY],
            )

    has_large_payout = False
    average_payout = (
        twin.total_amount / twin.amount_count
        if twin
        and twin.amount_count >= active_policy.amount_baseline_min_samples
        and twin.amount_count
        else None
    )
    for payout in payouts:
        is_large = payout.amount > active_policy.large_payout_threshold
        if is_large and average_payout:
            is_large = payout.amount >= active_policy.large_payout_relative_factor * average_payout
        if is_large:
            has_large_payout = True
            evidence.add(
                IntentEvidenceSource.PAYOUT,
                str(payout.payout_id),
                "A payout amount exceeded the configured large-payout rule.",
                as_utc(payout.executed_at or payout.created_at),
                [IntentSignalCode.LARGE_PAYOUT],
            )

    blocked_payout_count = 0
    has_decoy_routing = False
    for payout in payouts:
        status = payout.status.strip().lower()
        provider = (payout.provider_name or "").strip().lower()
        if status in BLOCKED_PAYOUT_STATUSES:
            blocked_payout_count += 1
            evidence.add(
                IntentEvidenceSource.PAYOUT,
                str(payout.payout_id),
                "A payout was blocked or rejected by the server-side policy.",
                as_utc(payout.executed_at or payout.created_at),
                [IntentSignalCode.BLOCKED_PAYOUT],
            )
        if (
            status in DECOY_STATUSES
            or provider == "honey_synthetic_decoy"
            or provider.endswith("_decoy")
        ):
            has_decoy_routing = True
            evidence.add(
                IntentEvidenceSource.PAYOUT,
                str(payout.payout_id),
                "A payout was routed to a synthetic decoy destination.",
                as_utc(payout.executed_at or payout.created_at),
                [IntentSignalCode.DECOY_ROUTING],
            )

    if risk_state and risk_state.canary_seen:
        has_canary_interaction = True
        evidence.add(
            IntentEvidenceSource.RISK_STATE,
            f"{source.session.session_id}:canary",
            "The session risk ledger records a canary interaction.",
            risk_state.last_evaluated_at,
            [IntentSignalCode.CANARY_INTERACTION],
        )
    for canary in canaries:
        if canary.triggered_at is not None:
            has_canary_interaction = True
            evidence.add(
                IntentEvidenceSource.CANARY,
                str(canary.canary_id),
                "A canary resource associated with the session was triggered.",
                as_utc(canary.triggered_at),
                [IntentSignalCode.CANARY_INTERACTION],
            )
    for incident in incidents:
        if "CANARY" in incident.trigger_reason.upper():
            has_canary_interaction = True
            evidence.add(
                IntentEvidenceSource.INCIDENT,
                str(incident.incident_id),
                "An incident trigger reason records a canary interaction.",
                as_utc(incident.created_at),
                [IntentSignalCode.CANARY_INTERACTION],
            )

    session_revoked = session_status == "revoked"
    if session_revoked:
        evidence.add(
            IntentEvidenceSource.SESSION,
            str(source.session.session_id),
            "The session is in a revoked state.",
            source.session.last_activity_at,
            [IntentSignalCode.SESSION_REVOKED],
        )

    baseline_occurred_at = source.session.last_activity_at or (
        as_utc(events[-1].occurred_at) if events else None
    )
    if baseline_ready:
        evidence.add(
            IntentEvidenceSource.SESSION,
            str(source.session.session_id),
            "The identity behavioural baseline is established for novelty checks.",
            baseline_occurred_at,
            [IntentSignalCode.BASELINE_MATURE],
        )
    else:
        evidence.add(
            IntentEvidenceSource.SESSION,
            str(source.session.session_id),
            "The identity behavioural baseline is provisional; novelty is not established.",
            baseline_occurred_at,
            [IntentSignalCode.BASELINE_PROVISIONAL],
        )
    if not events and not payouts:
        evidence.add(
            IntentEvidenceSource.SESSION,
            str(source.session.session_id),
            "The session has no supported events or payout records.",
            source.session.last_activity_at,
            [IntentSignalCode.NO_EVENTS],
        )

    return IntentSignals(
        session_id=source.session.session_id,
        event_count=len(events),
        unknown_event_count=unknown_event_count,
        auth_event_count=auth_count,
        mfa_event_count=mfa_count,
        security_anomaly_count=anomaly_count,
        pageview_count=pageview_count,
        heartbeat_count=heartbeat_count,
        payee_registration_count=len(registration_events),
        payout_event_count=len(payout_events),
        has_new_device=has_new_device,
        has_new_location=has_new_location,
        has_unusual_time=has_unusual_time,
        has_new_payee=has_new_payee,
        has_large_payout=has_large_payout,
        has_payee_add_then_payout=has_payee_add_then_payout,
        has_payee_registration_velocity=has_registration_velocity,
        has_payout_velocity=has_payout_velocity,
        has_canary_interaction=has_canary_interaction,
        has_decoy_routing=has_decoy_routing,
        blocked_payout_count=blocked_payout_count,
        session_trust_level=session_trust,
        session_status=session_status,
        session_risk_score=source.session.risk_score,
        session_revoked=session_revoked,
        baseline_ready=baseline_ready,
        baseline_provisional=baseline_provisional,
        hour_baseline_ready=hour_baseline_ready,
        has_payout_activity=bool(payouts or payout_events),
        max_payee_registrations_in_window=max_registrations,
        max_payouts_in_window=max_payouts,
        first_event_at=as_utc(events[0].occurred_at) if events else None,
        last_event_at=as_utc(events[-1].occurred_at) if events else None,
        evidence=evidence.items(),
    )
