"""Deterministic behavioural feature extraction.

Feature extraction is a pure function of the evaluation request, the identity
twin baseline and the current session ledger. No randomness, no network calls
and no wall-clock lookups beyond the supplied timestamp.
"""

from datetime import datetime, timezone

from app.risk.config import RiskConfig
from app.risk.schemas import FeatureVector, RiskEvaluationRequest, SessionRiskState, TwinSnapshot
from app.risk.timezones import local_hour, resolve_timezone
from app.risk.twin import (
    confirmed_payees,
    device_is_known,
    hash_device,
    hash_recipient,
    location_is_known,
    pending_payees,
    resolve_location_bucket,
)

# Client supplied deviation flags are never trusted. The server derives every
# signal from the identity twin baseline and the request facts. A flag that is
# present in the payload is ignored and reported as a note so that a client
# attempt to assert (or to suppress) its own risk profile is visible in the
# evaluation record.
_CLIENT_FLAGS: dict[str, tuple[str, ...]] = {
    "device": ("is_new_device", "new_device"),
    "location": ("is_new_location", "new_location", "location_mismatch"),
    "time": ("is_unusual_time", "unusual_hour"),
    "payee": ("is_new_payee", "new_payee", "new_recipient"),
    "large_payout": ("is_large_payout", "large_payout"),
}

PAYEE_REGISTRATION_ACTIONS = frozenset({"payee.add", "payee.added", "add_payee"})
PAYEE_REGISTRATION_EVENT_TYPES = frozenset({"payee.added"})


def _ignored_client_flags(context: dict) -> list[str]:
    """Return the client supplied risk flags that were ignored."""
    ignored: list[str] = []
    for dimension, keys in _CLIENT_FLAGS.items():
        if any(context.get(key) is True for key in keys):
            ignored.append(dimension)
    return ignored


def is_payee_registration(event_type: str, action_type: str) -> bool:
    return (
        event_type in PAYEE_REGISTRATION_EVENT_TYPES
        or action_type.lower() in PAYEE_REGISTRATION_ACTIONS
    )


def is_payout_event(event_type: str, action_type: str) -> bool:
    return action_type.lower() == "payout" or event_type.startswith("payout.")


def extract_features(
    request: RiskEvaluationRequest,
    twin: TwinSnapshot,
    state: SessionRiskState,
    config: RiskConfig,
    now: datetime | None = None,
) -> FeatureVector:
    """Build the deterministic feature vector for a single evaluation."""
    moment = now or datetime.now(timezone.utc)
    context = request.context or {}

    event_type = (request.event_type or context.get("event_type") or "").strip()
    action_type = (request.action_type or "").strip()

    occurred_at = request.occurred_at or moment
    tz = resolve_timezone(config.default_timezone)
    hour = local_hour(occurred_at, tz)

    device_hash = hash_device(
        request.device_id or context.get("device_id"), config.device_hash_salt
    )
    location_bucket = resolve_location_bucket(
        context, request.ip_address or context.get("ip_address")
    )
    recipient_hash = hash_recipient(
        request.recipient or context.get("recipient_email") or context.get("recipient")
    )

    provisional = twin.sample_count < config.min_samples
    known_payees = confirmed_payees(twin, config) | pending_payees(twin, config)
    session_registered = set(state.registered_payees)

    notes: list[str] = []
    for dimension in _ignored_client_flags(context):
        notes.append(f"CLIENT_RISK_FLAG_IGNORED:{dimension}")

    is_new_device = bool(device_hash and not device_is_known(twin, device_hash, config))

    is_new_location = bool(location_bucket and not location_is_known(twin, location_bucket, config))

    hour_total = sum(twin.hour_histogram.values())
    baseline_ready = (
        twin.sample_count >= config.min_samples and hour_total >= config.min_hour_samples
    )
    hour_count = twin.hour_histogram.get(str(hour), 0)
    hour_share = (hour_count / hour_total) if hour_total else 0.0
    hour_concentration = (max(twin.hour_histogram.values()) / hour_total) if hour_total else 0.0
    # An hour is unusual while it is not established for the identity and it
    # is not one of the hours that carry the bulk of the activity. The hour
    # histogram is learned from every learned event, so a legitimate hour
    # stops being unusual after a couple of observations while an hour that
    # only ever appears with an unknown device or location stays unusual.
    #
    # The hour model only applies to identities with a concentrated time of
    # day profile. An identity that is active around the clock has no
    # meaningful hour baseline, so "this hour is new" carries no evidence and
    # the signal stays switched off instead of flagging the first visit to
    # every additional business hour.
    hour_model_applies = hour_concentration >= config.hour_concentration_min
    hour_established = hour_count >= config.hour_confirm_observations
    hour_is_active = hour_share >= config.active_hour_fraction
    is_unusual_hour = bool(
        baseline_ready and hour_model_applies and not hour_established and not hour_is_active
    )

    registration = is_payee_registration(event_type, action_type)
    payout = is_payout_event(event_type, action_type)

    if recipient_hash:
        unseen = recipient_hash not in known_payees and recipient_hash not in session_registered
        if registration:
            # A newly registered payee is the primary NEW_PAYEE trigger.
            is_new_payee = unseen
        else:
            # For payouts the baseline must be established, otherwise a cold
            # start would flag every first payout as a new payee.
            established = not provisional and bool(confirmed_payees(twin, config))
            is_new_payee = bool(unseen and established)
            if unseen and not established and not provisional:
                notes.append("NEW_PAYEE_BASELINE_NOT_ESTABLISHED")
    else:
        is_new_payee = False

    is_large_payout = request.amount > config.large_payout_threshold
    if is_large_payout and twin.amount_count >= config.amount_baseline_min_samples:
        # A payout that is large for the market but normal for this identity is
        # not a large payout for this identity. The relative check keeps
        # merchants with a naturally high payout volume from being permanently
        # elevated while still catching a genuine spike.
        average_payout = twin.total_amount / twin.amount_count
        is_large_payout = request.amount >= (config.large_payout_relative_factor * average_payout)

    return FeatureVector(
        event_type=event_type,
        action_type=action_type,
        amount=float(request.amount),
        recipient_hash=recipient_hash,
        device_hash=device_hash,
        location_bucket=location_bucket,
        local_hour=hour,
        is_payee_registration=registration,
        is_payout=payout,
        is_new_device=is_new_device,
        is_new_location=is_new_location,
        is_unusual_hour=is_unusual_hour,
        is_new_payee=is_new_payee,
        is_large_payout=is_large_payout,
        twin_provisional=provisional,
        twin_sample_count=twin.sample_count,
        baseline_ready=baseline_ready,
        notes=notes,
    )
