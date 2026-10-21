import uuid
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.payouts import PayoutRequest


class ProviderPayoutResult(BaseModel):
    success: bool
    provider_name: str
    provider_transaction_id: str
    environment: str = Field(
        description="Environment indicator, e.g. 'synthetic_mock' or 'paypal_sandbox'"
    )
    details: dict[str, Any] = Field(default_factory=dict)
    executed_at: datetime


class IPaymentProviderAdapter(Protocol):
    """Protocol for protected payment provider adapters."""

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult: ...


class MockPaymentProviderAdapter:
    """
    Safe mock adapter for automated testing and local development.

    CRITICAL INVARIANT:
    Returns unmistakably synthetic transaction references.
    Must NEVER claim a real PayPal transaction occurred.
    """

    def __init__(self):
        self.invocation_count = 0
        self.executed_transactions = []

    def reset(self) -> None:
        self.invocation_count = 0
        self.executed_transactions.clear()

    def execute_payout(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocation_count += 1
        synth_tx_id = f"SYNTH-MOCK-TXN-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        result = ProviderPayoutResult(
            success=True,
            provider_name="mock_adapter",
            provider_transaction_id=synth_tx_id,
            environment="synthetic_mock",
            details={
                "mock_warning": "SYNTHETIC SIMULATION ONLY. NO REAL MONEY MOVED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
                "invocation_number": self.invocation_count,
            },
            executed_at=now,
        )
        self.executed_transactions.append(result)
        return result


class DecoyHoneyAdapter:
    """
    Synthetic honey-workspace provider adapter.
    Handles sessions routed to DECOY.
    Never moves funds or contacts PayPal.
    """

    def __init__(self):
        self.invocation_count = 0

    def execute_decoy(self, request: PayoutRequest, merchant_id: UUID) -> ProviderPayoutResult:
        self.invocation_count += 1
        decoy_tx_id = f"HONEY-DECOY-SIM-TXN-{uuid.uuid4().hex[:12].upper()}"
        now = datetime.now(timezone.utc)

        return ProviderPayoutResult(
            success=True,
            provider_name="honey_synthetic_decoy",
            provider_transaction_id=decoy_tx_id,
            environment="honey_sandbox_simulation",
            details={
                "honey_warning": "CONFINEMENT SIMULATION. DECOY WORKSPACE ENGAGED.",
                "recipient": request.recipient_email,
                "amount": request.amount,
                "currency": request.currency,
                "merchant_id": str(merchant_id),
            },
            executed_at=now,
        )


mock_provider_instance = MockPaymentProviderAdapter()
decoy_provider_instance = DecoyHoneyAdapter()


def get_payment_provider() -> IPaymentProviderAdapter:
    return mock_provider_instance


def get_decoy_provider() -> DecoyHoneyAdapter:
    return decoy_provider_instance
