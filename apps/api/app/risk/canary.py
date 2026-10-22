"""Canary / honeypot detection.

A canary interaction is an unambiguous, high-confidence compromise signal: it
forces level 3 isolation regardless of the accumulated score. Detection is
deliberately conservative and exact-match based so that normal traffic can
never be mistaken for a honeypot hit.
"""

from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from app.risk.schemas import RiskEvaluationRequest

# Action names that are unconditionally treated as a canary interaction.
CANARY_ACTIONS: frozenset[str] = frozenset({"canary.trap", "canary_interaction", "canary_trigger"})

# Context keys inspected for a canary identifier.
CANARY_TOKEN_KEYS: tuple[str, ...] = (
    "canary_token",
    "canary_id",
    "trap_signature",
    "honeypot_token",
)


@runtime_checkable
class CanaryRegistry(Protocol):
    """Lookup contract for known canary identifiers."""

    def is_canary(self, identifier: str) -> bool: ...


class InMemoryCanaryRegistry:
    """Default registry backed by an immutable set of exact identifiers."""

    def __init__(self, identifiers: Iterable[str] = ()) -> None:
        self._identifiers = frozenset(
            identifier.strip() for identifier in identifiers if identifier and identifier.strip()
        )

    @property
    def identifiers(self) -> frozenset[str]:
        return self._identifiers

    def is_canary(self, identifier: str) -> bool:
        if not identifier:
            return False
        return identifier.strip() in self._identifiers


def detect_canary(request: RiskEvaluationRequest, registry: CanaryRegistry) -> bool:
    """Return True when the request represents a canary / honeypot interaction.

    Only two server verifiable paths are accepted:

    * the honey workspace reports the trap through the ``canary.trap`` action,
    * the request carries a canary identifier (token or payout recipient)
      that is present in the server side registry.

    A plain boolean in the client payload is never trusted: a client must not
    be able to assert its own compromise state.
    """
    context = request.context or {}

    if request.action_type in CANARY_ACTIONS:
        return True

    for key in CANARY_TOKEN_KEYS:
        token = context.get(key)
        if isinstance(token, str) and registry.is_canary(token):
            return True

    if request.recipient and registry.is_canary(request.recipient):
        return True

    return False
