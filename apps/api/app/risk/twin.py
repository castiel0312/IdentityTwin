"""Pure behavioural twin helpers: hashing, location bucketing and baseline updates.

Everything in this module is deterministic and free of I/O so the calibration
harness can replay synthetic identities without a database.
"""

import hashlib
import ipaddress
from datetime import datetime

from app.risk.config import RiskConfig
from app.risk.schemas import FeatureVector, TwinSnapshot


def hash_device(device_id: str | None, salt: str) -> str | None:
    """Hash a raw device fingerprint with the configured salt.

    Raw device identifiers are never persisted; only the salted SHA-256 digest
    is stored on the twin.
    """
    if not device_id:
        return None
    digest = hashlib.sha256(f"{salt}:{device_id.strip()}".encode()).hexdigest()
    return digest


def hash_recipient(recipient: str | None) -> str | None:
    """Hash a payout recipient so payee baselines never store raw contact data."""
    if not recipient:
        return None
    normalized = recipient.strip().lower()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode()).hexdigest()


def bucket_ip_address(ip_address: str | None) -> str | None:
    """Bucket an IP address into a coarse network prefix.

    IPv4 addresses collapse to their /16 prefix and IPv6 addresses to their
    /32 prefix. No geo-location service is contacted.
    """
    if not ip_address:
        return None
    try:
        parsed = ipaddress.ip_address(ip_address.strip())
    except ValueError:
        return None
    if parsed.version == 4:
        return ".".join(parsed.exploded.split(".")[:2])
    return ":".join(parsed.exploded.split(":")[:4])


def resolve_location_bucket(context: dict, ip_address: str | None) -> str | None:
    """Resolve the location bucket for an event.

    An explicit location supplied by the caller always wins. Otherwise the
    coarse network prefix of the client IP is used.
    """
    for key in ("location", "geo_bucket", "location_bucket", "city"):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()[:64]
    return bucket_ip_address(ip_address)


def twin_is_provisional(twin: TwinSnapshot, config: RiskConfig) -> bool:
    """True while the twin has not collected enough baseline observations."""
    return twin.sample_count < config.min_samples


def confirmed_payees(twin: TwinSnapshot, config: RiskConfig) -> set[str]:
    return twin.confirmed_payees(config.payee_confirm_observations)


def pending_payees(twin: TwinSnapshot, config: RiskConfig) -> set[str]:
    return twin.pending_payees(config.payee_confirm_observations)


def device_is_known(twin: TwinSnapshot, device_hash: str | None, config: RiskConfig) -> bool:
    """True when the device was observed often enough to be part of the baseline."""
    if not device_hash:
        return True
    return twin.device_observations.get(device_hash, 0) >= config.context_confirm_observations


def location_is_known(twin: TwinSnapshot, location_bucket: str | None, config: RiskConfig) -> bool:
    """True when the location was observed often enough to be part of the baseline."""
    if not location_bucket:
        return True
    return twin.location_observations.get(location_bucket, 0) >= config.context_confirm_observations


def _trim(values: list[str], limit: int) -> list[str]:
    if len(values) <= limit:
        return values
    return values[-limit:]


def _trim_payees(observations: dict[str, int], limit: int) -> dict[str, int]:
    if len(observations) <= limit:
        return observations
    ordered = sorted(observations.items(), key=lambda item: (-item[1], item[0]))
    return dict(ordered[:limit])


def apply_observation(
    twin: TwinSnapshot,
    features: FeatureVector,
    config: RiskConfig,
    now: datetime,
) -> TwinSnapshot:
    """Return an updated twin with one benign observation applied.

    The full observation covers the parts of the baseline that describe *when*
    and *how often* the identity acts: the sample count and the hour of day
    distribution. The payout size statistics are maintained separately by
    :func:`apply_amount_observation`, so that the amount baseline can be fed
    by an event that is only unusual in size without teaching the twin that
    an unusual hour or an unusual amount is normal.

    The input twin is never mutated; a new snapshot is returned so callers can
    diff or persist it atomically.
    """
    updated = twin.model_copy(
        update={
            "confirmed_devices": list(twin.confirmed_devices),
            "confirmed_locations": list(twin.confirmed_locations),
            "payee_observations": dict(twin.payee_observations),
            "device_observations": dict(twin.device_observations),
            "location_observations": dict(twin.location_observations),
            "hour_histogram": dict(twin.hour_histogram),
        }
    )
    updated.sample_count += 1

    if features.local_hour is not None:
        hour_key = str(features.local_hour)
        updated.hour_histogram[hour_key] = updated.hour_histogram.get(hour_key, 0) + 1

    updated.last_updated_at = now
    return updated


def apply_amount_observation(
    twin: TwinSnapshot,
    features: FeatureVector,
    config: RiskConfig,
    now: datetime,
) -> TwinSnapshot:
    """Return an updated twin with the payout size of one event applied.

    The average payout of an identity is what makes a large payout relative
    to its own normal behaviour. It is therefore learned from every event that
    comes from the established context, even when the event is only unusual in
    size or in timing. Events that carry a novelty signal (new device, new
    location, new payee, a payee-add-then-payout sequence or a canary hit)
    never contribute, so a hostile context cannot inflate the baseline.
    """
    updated = twin.model_copy(
        update={
            "confirmed_devices": list(twin.confirmed_devices),
            "confirmed_locations": list(twin.confirmed_locations),
            "payee_observations": dict(twin.payee_observations),
            "device_observations": dict(twin.device_observations),
            "location_observations": dict(twin.location_observations),
            "hour_histogram": dict(twin.hour_histogram),
        }
    )

    if features.amount > 0:
        updated.total_amount += features.amount
        updated.amount_count += 1

    updated.last_updated_at = now
    return updated


def apply_context_observations(
    twin: TwinSnapshot,
    features: FeatureVector,
    config: RiskConfig,
    now: datetime,
) -> TwinSnapshot:
    """Count one observation of the device, location and payee of an event.

    A device, location or payee becomes part of the identity baseline once it
    has been observed ``context_confirm_observations`` times. Counting the
    observation keeps legitimate context expansion (a second phone, a second
    office) from being flagged forever, while a single hostile session never
    reaches the confirmation threshold because the engine refuses to count
    observations from sessions that carry session scoped anomalies.
    """
    updated = twin.model_copy(
        update={
            "confirmed_devices": list(twin.confirmed_devices),
            "confirmed_locations": list(twin.confirmed_locations),
            "payee_observations": dict(twin.payee_observations),
            "device_observations": dict(twin.device_observations),
            "location_observations": dict(twin.location_observations),
            "hour_histogram": dict(twin.hour_histogram),
        }
    )

    if features.device_hash:
        count = updated.device_observations.get(features.device_hash, 0) + 1
        updated.device_observations[features.device_hash] = count
        if (
            count >= config.context_confirm_observations
            and features.device_hash not in updated.confirmed_devices
        ):
            updated.confirmed_devices = _trim(
                [*updated.confirmed_devices, features.device_hash],
                config.max_tracked_devices,
            )

    if features.location_bucket:
        count = updated.location_observations.get(features.location_bucket, 0) + 1
        updated.location_observations[features.location_bucket] = count
        if (
            count >= config.context_confirm_observations
            and features.location_bucket not in updated.confirmed_locations
        ):
            updated.confirmed_locations = _trim(
                [*updated.confirmed_locations, features.location_bucket],
                config.max_tracked_locations,
            )

    if features.recipient_hash:
        current = updated.payee_observations.get(features.recipient_hash, 0)
        updated.payee_observations[features.recipient_hash] = current + 1
        updated.payee_observations = _trim_payees(
            updated.payee_observations, config.max_tracked_payees
        )

    updated.last_updated_at = now
    return updated
