from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidWebhookSignatureException
from app.db.repositories.idempotency_repo import IdempotencyRepository
from app.db.session import get_db
from app.gateway.provider import IPaymentProviderAdapter, get_payment_provider
from app.models.idempotency import IdempotencyRecord

router = APIRouter(prefix="/webhooks", tags=["PayPal Webhooks & Reconciliations"])


@router.post(
    "/paypal",
    status_code=status.HTTP_200_OK,
    summary="Receive and verify incoming PayPal Sandbox webhook events",
    description=(
        "Verifies cryptographic signature against PayPal Sandbox API. "
        "Enforces event idempotency and reconciles payout batch status. "
        "Unverified signatures are strictly rejected."
    ),
)
async def receive_paypal_webhook(
    request: Request,
    db: Session = Depends(get_db),
    provider: IPaymentProviderAdapter = Depends(get_payment_provider),
) -> dict[str, Any]:
    # 1. Read raw body and headers
    raw_body = await request.body()
    headers = dict(request.headers)

    # 2. Cryptographic signature verification
    is_valid = provider.verify_webhook_signature(headers=headers, raw_body=raw_body)
    if not is_valid:
        raise InvalidWebhookSignatureException(
            message="PayPal webhook cryptographic signature verification failed.",
            code="INVALID_WEBHOOK_SIGNATURE",
            details={"transmission_id": headers.get("paypal-transmission-id")},
        )

    # Parse JSON payload
    try:
        event_payload = await request.json()
    except Exception:
        event_payload = {}

    event_id = event_payload.get("id") or headers.get("paypal-transmission-id") or "UNKNOWN_EVENT"
    event_type = event_payload.get("event_type", "UNKNOWN_TYPE")
    resource = event_payload.get("resource", {})

    # 3. Idempotent deduplication check
    idempotency_repo = IdempotencyRepository(db)
    # Use deterministic system merchant UUID for platform-wide webhook deduplication
    import uuid

    system_merchant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    webhook_key = f"paypal-webhook-{event_id}"

    existing_rec = idempotency_repo.get_record(system_merchant_id, webhook_key)
    if existing_rec:
        return {
            "status": "duplicate",
            "message": "Webhook event was previously processed and reconciled.",
            "event_id": event_id,
            "event_type": event_type,
        }

    # Record processing state
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    record = IdempotencyRecord(
        idempotency_key=webhook_key,
        merchant_id=system_merchant_id,
        request_hash=event_id,
        status="completed",
        response_code=200,
        response_payload={"event_id": event_id, "event_type": event_type},
        expires_at=now + timedelta(days=7),
    )
    idempotency_repo.save_record(record)

    # 4. Reconcile payout status if applicable
    batch_header = resource.get("batch_header", {})
    payout_batch_id = batch_header.get("payout_batch_id") or resource.get("payout_batch_id")

    if payout_batch_id:
        from sqlalchemy import select

        from app.models.payout import PayoutRequestRecord

        stmt = select(PayoutRequestRecord).where(
            PayoutRequestRecord.provider_reference == str(payout_batch_id)
        )
        payout = db.scalars(stmt).first()
        if payout:
            if event_type in (
                "PAYMENT.PAYOUTSBATCH.SUCCESS",
                "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            ):
                payout.status = "reconciled_completed"
                db.commit()
            elif event_type in (
                "PAYMENT.PAYOUTSBATCH.DENIED",
                "PAYMENT.PAYOUTS-ITEM.BLOCKED",
                "PAYMENT.PAYOUTS-ITEM.DENIED",
            ):
                payout.status = "provider_denied"
                db.commit()

    return {
        "status": "processed",
        "event_id": event_id,
        "event_type": event_type,
        "message": "PayPal webhook event verified, deduplicated, and reconciled successfully.",
    }
