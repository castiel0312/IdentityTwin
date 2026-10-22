"""Timezone resolution helpers for hour-of-day behavioural baselines.

Windows Python distributions frequently ship without the IANA ``tzdata``
package, so ``zoneinfo.ZoneInfo`` can raise ``ZoneInfoNotFoundError``. The
engine must stay deterministic and dependency free, therefore a small table of
fixed standard-time offsets is used as a fallback. The fallback ignores
daylight saving transitions, which is documented as a known limitation.
"""

from datetime import timedelta, timezone, tzinfo
from functools import lru_cache

try:  # pragma: no cover - availability depends on the platform
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - Python < 3.9 is unsupported anyway
    ZoneInfo = None  # type: ignore[assignment]

# Standard-time offsets (minutes from UTC) used when IANA data is unavailable.
_FALLBACK_OFFSETS_MINUTES: dict[str, int] = {
    "UTC": 0,
    "Etc/UTC": 0,
    "Asia/Kolkata": 330,
    "Asia/Calcutta": 330,
    "Asia/Singapore": 480,
    "Asia/Dubai": 240,
    "Asia/Tokyo": 540,
    "Asia/Shanghai": 480,
    "Europe/London": 60,
    "Europe/Berlin": 120,
    "Europe/Paris": 120,
    "America/New_York": -300,
    "America/Chicago": -360,
    "America/Denver": -420,
    "America/Los_Angeles": -480,
    "Australia/Sydney": 600,
}


class FixedOffsetTimezone(tzinfo):
    """Minimal fixed-offset timezone used when IANA data is unavailable."""

    def __init__(self, offset_minutes: int, name: str) -> None:
        self._offset = timedelta(minutes=offset_minutes)
        self._name = name

    def utcoffset(self, dt):  # noqa: ANN001, ANN201 - stdlib tzinfo signature
        return self._offset

    def dst(self, dt):  # noqa: ANN001, ANN201 - stdlib tzinfo signature
        return timedelta(0)

    def tzname(self, dt):  # noqa: ANN001, ANN201 - stdlib tzinfo signature
        return self._name

    def __repr__(self) -> str:
        return f"FixedOffsetTimezone({self._name!r})"


@lru_cache(maxsize=32)
def resolve_timezone(name: str | None) -> tzinfo:
    """Resolve an IANA timezone name to a concrete ``tzinfo``.

    Falls back to a fixed offset table and finally to UTC so that the risk
    engine never fails closed because of a missing platform timezone database.

    The result is cached: resolving a timezone can be expensive (a failing
    ``ZoneInfo`` lookup probes the import system for the ``tzdata`` package on
    every call) and the mapping never changes during a process lifetime.
    """
    if not name:
        return timezone.utc
    if ZoneInfo is not None:
        try:
            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - ZoneInfo raises several error types
            pass
    minutes = _FALLBACK_OFFSETS_MINUTES.get(name)
    if minutes is None:
        return timezone.utc
    return FixedOffsetTimezone(minutes, name)


def local_hour(timestamp, tz: tzinfo) -> int:
    """Return the merchant-local hour (0-23) for an aware or naive datetime."""
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(tz).hour
