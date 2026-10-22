"""Deterministic synthetic identity cohorts used for calibration.

The generator is deliberately free of wall clock time and of global random
state: the same seed always produces the same data, byte for byte, which makes
the committed fixture reproducible, diffable and safe to replay in CI.

The cohort mix mirrors the population that the engine has to survive:

======================  ======  ==============================================
cohort                  count   intent
======================  ======  ==============================================
regular                   400   ordinary daily activity
shift_based               150   activity concentrated in a night shift window
traveling                 120   legitimate movement between known locations
high_volume               120   many small events per session
high_value                100   large but legitimate payouts
new_sparse                120   cold start identities with a thin baseline
compromised               180   established identities that are attacked
slow_and_low               94   rare, small, but perfectly legitimate activity
======================  ======  ==============================================

The total is 1,284 identities.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

CohortLabel = Literal["benign", "compromised"]

#: Fixed anchor for every generated timestamp. Never use "now" here, otherwise
#: the committed fixture would change on every regeneration.
ANCHOR = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

COHORT_SIZES: dict[str, int] = {
    "regular": 400,
    "shift_based": 150,
    "traveling": 120,
    "high_volume": 120,
    "high_value": 100,
    "new_sparse": 120,
    "compromised": 180,
    "slow_and_low": 94,
}

TOTAL_IDENTITIES = sum(COHORT_SIZES.values())

ATTACK_TYPES: tuple[str, ...] = (
    "device_takeover",
    "payee_redirection",
    "canary_hit",
    "velocity_burst",
    "slow_and_low",
)

_LOCATIONS = ("BENGALURU", "MUMBAI", "PUNE", "DELHI", "HYDERABAD")
_SHIFT_HOURS = (22, 23, 0, 1, 2, 3, 4)
_DAY_HOURS = (8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19)


class SyntheticAttack(BaseModel):
    """Description of the hostile session attached to a compromised identity."""

    attack_type: str
    device_id: str | None = None
    location: str | None = None
    hour: int | None = None
    payee: str | None = None
    amount: float = 0.0


class SyntheticProfile(BaseModel):
    """Compact, serialisable description of one synthetic identity."""

    identity_id: str
    cohort: str
    label: CohortLabel
    devices: list[str]
    locations: list[str]
    active_hours: list[int]
    payees: list[str]
    sessions: int
    events_per_session: int
    typical_amount: float
    payout_per_session: int = 1
    attack: SyntheticAttack | None = None


class SyntheticEvent(BaseModel):
    """One synthetic event inside a synthetic session."""

    offset_minutes: int
    event_type: str
    action_type: str
    device_id: str | None = None
    ip_address: str | None = None
    location: str | None = None
    amount: float = 0.0
    recipient: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class SyntheticSession(BaseModel):
    """One synthetic session (one login session of an identity)."""

    index: int
    events: list[SyntheticEvent]


def _ip_for_device(device_id: str) -> str:
    """Derive a stable, documentation-only IPv4 address from a device id."""
    digest = sum(ord(char) for char in device_id)
    return f"198.51.{(digest // 251) % 256}.{digest % 251 + 1}"


def _attack_ip(identity_id: str) -> str:
    digest = sum(ord(char) for char in identity_id)
    return f"203.0.113.{digest % 250 + 1}"


def _cohort_hours(cohort: str, rng: random.Random) -> list[int]:
    if cohort == "shift_based":
        return sorted(_SHIFT_HOURS)
    if cohort == "slow_and_low":
        return [5, 6]
    if cohort == "high_value":
        return sorted(rng.sample(_DAY_HOURS, 6))
    return sorted(rng.sample(_DAY_HOURS, 10))


def _cohort_amount(cohort: str, rng: random.Random) -> float:
    if cohort == "high_value":
        return float(rng.randrange(6_000, 25_001, 500))
    if cohort == "high_volume":
        return float(rng.randrange(10, 201, 5))
    if cohort == "slow_and_low":
        return float(rng.randrange(20, 121, 5))
    if cohort == "new_sparse":
        return float(rng.randrange(40, 400, 10))
    return float(rng.randrange(100, 901, 25))


def _session_count(cohort: str) -> tuple[int, int]:
    if cohort == "new_sparse":
        return 3, 4
    if cohort == "slow_and_low":
        return 4, 3
    if cohort == "high_volume":
        return 10, 10
    return 8, 6


def build_profiles(seed: int) -> list[SyntheticProfile]:
    """Build the full, deterministic profile list for ``seed``."""
    profiles: list[SyntheticProfile] = []
    for cohort, size in COHORT_SIZES.items():
        for index in range(size):
            identity_id = f"{cohort}-{index:04d}"
            rng = random.Random(f"{seed}:{identity_id}")
            sessions, events_per_session = _session_count(cohort)
            device_count = 2 if cohort == "high_volume" else 1
            devices = [f"dev-{identity_id}-{n}" for n in range(device_count)]
            location_count = 2 if cohort == "traveling" else 1
            locations = list(rng.sample(_LOCATIONS, location_count))
            payee_count = 3 if cohort == "high_volume" else 2
            payees = [f"payee-{identity_id}-{n}@example.test" for n in range(payee_count)]
            attack: SyntheticAttack | None = None
            active_hours = _cohort_hours(cohort, rng)
            if cohort == "compromised":
                attack_type = ATTACK_TYPES[index % len(ATTACK_TYPES)]
                if attack_type == "slow_and_low":
                    # A genuine slow and low fraud pattern: the attacker stays
                    # on the identity's own device, in the identity's own
                    # location, during the identity's normal hours and moves a
                    # small amount. Nothing about the context is unusual, so
                    # only the payee novelty is left as evidence.
                    attack = SyntheticAttack(
                        attack_type=attack_type,
                        device_id=devices[0],
                        location=locations[0],
                        hour=active_hours[0],
                        payee=f"exfil-{identity_id}@evil.test",
                        amount=float(rng.randrange(40, 260, 10)),
                    )
                else:
                    attack = SyntheticAttack(
                        attack_type=attack_type,
                        device_id=f"dev-attack-{identity_id}",
                        location=rng.choice([loc for loc in _LOCATIONS if loc not in locations]),
                        hour=3 if attack_type == "device_takeover" else 11,
                        payee=f"exfil-{identity_id}@evil.test",
                        amount=7_500.0,
                    )
            profiles.append(
                SyntheticProfile(
                    identity_id=identity_id,
                    cohort=cohort,
                    label="compromised" if cohort == "compromised" else "benign",
                    devices=devices,
                    locations=locations,
                    active_hours=active_hours,
                    payees=payees,
                    sessions=sessions,
                    events_per_session=events_per_session,
                    typical_amount=_cohort_amount(cohort, rng),
                    payout_per_session=1,
                    attack=attack,
                )
            )
    return profiles


def _event(
    offset_minutes: int,
    event_type: str,
    action_type: str,
    device_id: str,
    location: str,
    amount: float = 0.0,
    recipient: str | None = None,
    context: dict[str, Any] | None = None,
) -> SyntheticEvent:
    payload: dict[str, Any] = {"location": location}
    if context:
        payload.update(context)
    return SyntheticEvent(
        offset_minutes=offset_minutes,
        event_type=event_type,
        action_type=action_type,
        device_id=device_id,
        ip_address=_ip_for_device(device_id),
        location=location,
        amount=amount,
        recipient=recipient,
        context=payload,
    )


def _baseline_session(
    profile: SyntheticProfile,
    rng: random.Random,
    index: int,
) -> SyntheticSession:
    device_id = profile.devices[index % len(profile.devices)]
    if profile.cohort == "traveling":
        location = profile.locations[index % len(profile.locations)]
    else:
        location = profile.locations[0]
    hour = rng.choice(profile.active_hours)
    base_offset = index * 24 * 60 + hour * 60

    events: list[SyntheticEvent] = []
    step = 0

    def add_login() -> None:
        nonlocal step
        events.append(
            _event(
                base_offset + step * 2,
                "auth.login",
                "auth.login",
                device_id,
                location,
            )
        )
        step += 1

    def add_pageview() -> None:
        nonlocal step
        events.append(
            _event(
                base_offset + step * 2,
                "navigation.pageview",
                "navigation.pageview",
                device_id,
                location,
            )
        )
        step += 1

    def add_payout(recipient: str, amount: float) -> None:
        nonlocal step
        events.append(
            _event(
                base_offset + step * 2,
                "payout.submit",
                "payout.submit",
                device_id,
                location,
                amount=amount,
                recipient=recipient,
            )
        )
        step += 1

    def add_payee_add(recipient: str) -> None:
        nonlocal step
        events.append(
            _event(
                base_offset + step * 2,
                "payee.added",
                "payee.add",
                device_id,
                location,
                recipient=recipient,
            )
        )
        step += 1

    add_login()
    add_pageview()

    if index == 0:
        # The very first session registers a payee. This is the only place
        # where a legitimate identity performs the "add payee then pay it"
        # pattern, so the sequence signal is expected exactly once per
        # identity and is reported as a known noise source.
        add_payee_add(profile.payees[0])
        if profile.cohort != "high_value":
            add_payout(profile.payees[0], profile.typical_amount)
    else:
        payee = profile.payees[index % len(profile.payees)]
        amount = profile.typical_amount
        if profile.cohort == "high_value":
            amount = float(rng.randrange(6_000, 25_001, 500))
        add_payout(payee, amount)

    while step < profile.events_per_session:
        if step % 2 == 0:
            add_pageview()
        else:
            add_login()

    return SyntheticSession(index=index, events=events)


def _attack_session(profile: SyntheticProfile, rng: random.Random) -> SyntheticSession:
    attack = profile.attack
    assert attack is not None
    index = profile.sessions
    base_offset = index * 24 * 60 + (attack.hour or 3) * 60
    location = attack.location or profile.locations[0]
    device_id = attack.device_id or profile.devices[0]
    if device_id in profile.devices:
        # The attacker uses the identity's own device, so the network origin
        # stays consistent with the baseline.
        ip_address = _ip_for_device(device_id)
    else:
        ip_address = _attack_ip(profile.identity_id)

    events: list[SyntheticEvent] = []

    def add(
        event_type: str,
        action_type: str,
        offset: int,
        amount: float = 0.0,
        recipient: str | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"location": location}
        if context:
            payload.update(context)
        events.append(
            SyntheticEvent(
                offset_minutes=base_offset + offset,
                event_type=event_type,
                action_type=action_type,
                device_id=device_id,
                ip_address=ip_address,
                location=location,
                amount=amount,
                recipient=recipient,
                context=payload,
            )
        )

    if attack.attack_type == "device_takeover":
        add("auth.login", "auth.login", 0)
        add("payee.added", "payee.add", 5, recipient=attack.payee)
        add("payout.submit", "payout.submit", 12, amount=attack.amount, recipient=attack.payee)
    elif attack.attack_type == "payee_redirection":
        add("payee.added", "payee.add", 0, recipient=attack.payee)
        add("payout.submit", "payout.submit", 8, amount=attack.amount, recipient=attack.payee)
    elif attack.attack_type == "canary_hit":
        add(
            "security.anomaly_detected",
            "canary.trap",
            0,
            context={"canary_token": "IT-CANARY-0001"},
        )
    elif attack.attack_type == "velocity_burst":
        for burst in range(3):
            add(
                "payee.added",
                "payee.add",
                burst * 2,
                recipient=f"{attack.payee}-{burst}",
            )
        add(
            "payout.submit",
            "payout.submit",
            12,
            amount=attack.amount,
            recipient=f"{attack.payee}-2",
        )
    else:  # slow_and_low
        add("payout.submit", "payout.submit", 0, amount=attack.amount, recipient=attack.payee)

    return SyntheticSession(index=index, events=events)


def expand_profile(profile: SyntheticProfile, seed: int) -> list[SyntheticSession]:
    """Expand a profile into its deterministic sessions and events."""
    rng = random.Random(f"{seed}:{profile.identity_id}:events")
    sessions = [_baseline_session(profile, rng, index) for index in range(profile.sessions)]
    if profile.attack is not None:
        sessions.append(_attack_session(profile, rng))
    return sessions


def build_dataset(seed: int) -> list[tuple[SyntheticProfile, list[SyntheticSession]]]:
    """Build the full dataset as ``(profile, sessions)`` pairs."""
    return [(profile, expand_profile(profile, seed)) for profile in build_profiles(seed)]


def profile_fixture(seed: int) -> dict[str, Any]:
    """Serialisable representation of the dataset (the committed fixture)."""
    return {
        "seed": seed,
        "generator": "app.risk.synthetic_data",
        "anchor": ANCHOR.isoformat(),
        "total_identities": TOTAL_IDENTITIES,
        "cohort_sizes": dict(COHORT_SIZES),
        "identities": [profile.model_dump(mode="json") for profile in build_profiles(seed)],
    }


def profiles_from_fixture(payload: dict[str, Any]) -> list[SyntheticProfile]:
    """Rebuild the profile list from a committed fixture."""
    return [SyntheticProfile.model_validate(item) for item in payload["identities"]]


def fixture_digest(payload: dict[str, Any]) -> str:
    """Stable digest of a fixture payload, used by the reproducibility test."""
    import hashlib
    import json

    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def event_time(offset_minutes: int) -> datetime:
    """Absolute timestamp of an event offset (minutes after the anchor)."""
    return ANCHOR + timedelta(minutes=offset_minutes)
