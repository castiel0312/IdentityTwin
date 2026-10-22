"""Immutable configuration for the deterministic behavioral twin risk engine.

The engine is intentionally configuration driven so that calibration can sweep
non-contractual knobs (thresholds, decay, sequence windows) without touching
signal weights. Signal weights are part of the published risk contract and are
not swept by the calibration harness.
"""

from dataclasses import dataclass, field

from app.core.config import Settings, settings


@dataclass(frozen=True)
class RiskConfig:
    """Resolved risk engine configuration."""

    weight_new_device: float
    weight_new_location: float
    weight_unusual_time: float
    weight_new_payee: float
    weight_large_payout: float
    weight_new_payee_large_payout: float
    weight_payee_add_then_payout: float
    weight_canary_interaction: float

    threshold_restricted: float
    threshold_decoy: float
    threshold_isolated: float
    baseline_score: float

    min_samples: int
    provisional_factor: float
    large_payout_threshold: float
    large_payout_relative_factor: float
    amount_baseline_min_samples: int
    active_hour_fraction: float
    min_hour_samples: int
    hour_confirm_observations: int
    hour_concentration_min: float
    context_confirm_observations: int
    sequence_window_seconds: int
    decay_points_per_event: float
    time_decay_enabled: bool
    default_timezone: str
    device_hash_salt: str
    max_tracked_devices: int
    max_tracked_locations: int
    max_tracked_payees: int
    max_event_fingerprints: int
    payee_confirm_observations: int
    protected_actions: frozenset[str] = field(default_factory=frozenset)
    canary_identifiers: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_settings(cls, source: Settings | None = None) -> "RiskConfig":
        cfg = source or settings
        return cls(
            weight_new_device=cfg.RISK_WEIGHT_NEW_DEVICE,
            weight_new_location=cfg.RISK_WEIGHT_NEW_LOCATION,
            weight_unusual_time=cfg.RISK_WEIGHT_UNUSUAL_TIME,
            weight_new_payee=cfg.RISK_WEIGHT_NEW_PAYEE,
            weight_large_payout=cfg.RISK_WEIGHT_LARGE_PAYOUT,
            weight_new_payee_large_payout=cfg.RISK_WEIGHT_NEW_PAYEE_LARGE_PAYOUT,
            weight_payee_add_then_payout=cfg.RISK_WEIGHT_PAYEE_ADD_THEN_PAYOUT,
            weight_canary_interaction=cfg.RISK_WEIGHT_CANARY_INTERACTION,
            threshold_restricted=cfg.RISK_THRESHOLD_RESTRICTED,
            threshold_decoy=cfg.RISK_THRESHOLD_DECOY,
            threshold_isolated=cfg.RISK_THRESHOLD_ISOLATED,
            baseline_score=cfg.RISK_BASELINE_SCORE,
            min_samples=cfg.RISK_MIN_SAMPLES,
            provisional_factor=cfg.RISK_PROVISIONAL_FACTOR,
            large_payout_threshold=cfg.RISK_LARGE_PAYOUT_THRESHOLD,
            large_payout_relative_factor=cfg.RISK_LARGE_PAYOUT_RELATIVE_FACTOR,
            amount_baseline_min_samples=cfg.RISK_AMOUNT_BASELINE_MIN_SAMPLES,
            active_hour_fraction=cfg.RISK_ACTIVE_HOUR_FRACTION,
            min_hour_samples=cfg.RISK_MIN_HOUR_SAMPLES,
            hour_confirm_observations=cfg.RISK_HOUR_CONFIRM_OBSERVATIONS,
            hour_concentration_min=cfg.RISK_HOUR_CONCENTRATION_MIN,
            context_confirm_observations=cfg.RISK_CONTEXT_CONFIRM_OBSERVATIONS,
            sequence_window_seconds=cfg.RISK_SEQUENCE_WINDOW_SECONDS,
            decay_points_per_event=cfg.RISK_DECAY_POINTS_PER_EVENT,
            time_decay_enabled=cfg.RISK_TIME_DECAY_ENABLED,
            default_timezone=cfg.RISK_DEFAULT_TIMEZONE,
            device_hash_salt=cfg.RISK_DEVICE_HASH_SALT,
            max_tracked_devices=cfg.RISK_MAX_TRACKED_DEVICES,
            max_tracked_locations=cfg.RISK_MAX_TRACKED_LOCATIONS,
            max_tracked_payees=cfg.RISK_MAX_TRACKED_PAYEES,
            max_event_fingerprints=cfg.RISK_MAX_EVENT_FINGERPRINTS,
            payee_confirm_observations=cfg.RISK_PAYEE_CONFIRM_OBSERVATIONS,
            protected_actions=frozenset(
                a.strip().lower() for a in cfg.RISK_PROTECTED_ACTIONS.split(",") if a.strip()
            ),
            canary_identifiers=frozenset(
                c.strip() for c in cfg.RISK_CANARY_IDENTIFIERS.split(",") if c.strip()
            ),
        )


def get_risk_config() -> RiskConfig:
    """Return the process-wide resolved risk configuration."""
    return RiskConfig.from_settings(settings)
