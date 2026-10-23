import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidWebhookSignatureException
from app.db.repositories.idempotency_repo import IdempotencyRepository
from app.db.session import get_db
from app.gateway.webhooks import verify_webhook_signature
from app.models.idempotency import IdempotencyRecord
from app.models.payout import PayoutRequestRecord
from app.models.principal import Merchant

router = APIRouter(prefix="/webhooks", tags=["PayPal Webhooks & Reconciliations"])

# PayPal webhook events are platform-wide, not merchant-scoped. The
# idempotency table enforces a foreign key to `merchants`, so deduplication
# uses one persisted system merchant row instead of an unseeded UUID. Without
# that row PostgreSQL rejects every verified webhook with a foreign key error
# (SQLite test runs used to hide this because foreign keys were disabled).
WEBHOOK_SYSTEM_MERCHANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000000")
WEBHOOK_SYSTEM_MERCHANT_SLUG = "__identitytwin_webhooks__"


def _ensure_webhook_system_merchant(db: Session) -> None:
    if db.get(Merchant, WEBHOOK_SYSTEM_MERCHANT_ID) is not None:
        return
    db.add(
        Merchant(
            merchant_id=WEBHOOK_SYSTEM_MERCHANT_ID,
            name="IdentityTwin Webhook Platform",
            slug=WEBHOOK_SYSTEM_MERCHANT_SLUG,
            is_active=False,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # A concurrent webhook request may have created the row first.
        db.rollback()
        if db.get(Merchant, WEBHOOK_SYSTEM_MERCHANT_ID) is None:
            raise


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
) -> dict[str, Any]:
    # 1. Read raw body and headers
    raw_body = await request.body()
    headers = dict(request.headers)

    # 2. Cryptographic signature verification via Trust Gateway
    is_valid = verify_webhook_signature(headers=headers, raw_body=raw_body)
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
    if not isinstance(event_payload, dict):
        event_payload = {}

    event_id = event_payload.get("id") or headers.get("paypal-transmission-id")
    if not event_id:
        # A verified event is expected to carry an id. Falling back to the
        # event body digest still gives each distinct delivery its own
        # deduplication key instead of collapsing all of them into one.
        event_id = f"body-{hashlib.sha256(raw_body).hexdigest()}"
    event_type = event_payload.get("event_type", "UNKNOWN_TYPE")
    resource = event_payload.get("resource")
    if not isinstance(resource, dict):
        resource = {}

    # 3. Idempotent deduplication check
    idempotency_repo = IdempotencyRepository(db)
    webhook_key = f"paypal-webhook-{event_id}"

    existing_rec = idempotency_repo.get_record(WEBHOOK_SYSTEM_MERCHANT_ID, webhook_key)
    if existing_rec:
        return {
            "status": "duplicate",
            "message": "Webhook event was previously processed and reconciled.",
            "event_id": event_id,
            "event_type": event_type,
        }

    # The platform-wide dedup record has a foreign key to merchants. Ensure the
    # system merchant exists before writing anything in this transaction.
    _ensure_webhook_system_merchant(db)

    # 4. Reconcile payout status if applicable
    batch_header = resource.get("batch_header")
    if not isinstance(batch_header, dict):
        batch_header = {}
    payout_batch_id = batch_header.get("payout_batch_id") or resource.get("payout_batch_id")

    reconciled_status = None
    reconciled_payout_id = None
    if payout_batch_id:
        stmt = select(PayoutRequestRecord).where(
            PayoutRequestRecord.provider_reference == str(payout_batch_id)
        )
        payout = db.scalars(stmt).first()
        if payout:
            reconciled_payout_id = str(payout.payout_id)
            if event_type in (
                "PAYMENT.PAYOUTSBATCH.SUCCESS",
                "PAYMENT.PAYOUTS-ITEM.SUCCEEDED",
            ):
                payout.status = "reconciled_completed"
                reconciled_status = payout.status
            elif event_type in (
                "PAYMENT.PAYOUTSBATCH.DENIED",
                "PAYMENT.PAYOUTS-ITEM.BLOCKED",
                "PAYMENT.PAYOUTS-ITEM.DENIED",
            ):
                payout.status = "provider_denied"
                reconciled_status = payout.status

    # Save the deduplication record and the reconciled payout status in one
    # transaction. A crash must not leave an event marked processed while the
    # payout status was not updated.
    now = datetime.now(timezone.utc)
    record = IdempotencyRecord(
        idempotency_key=webhook_key,
        merchant_id=WEBHOOK_SYSTEM_MERCHANT_ID,
        request_hash=hashlib.sha256(raw_body).hexdigest(),
        status="completed",
        response_code=200,
        response_payload={
            "event_id": event_id,
            "event_type": event_type,
            "payout_id": reconciled_payout_id,
            "reconciled_status": reconciled_status,
        },
        expires_at=now + timedelta(days=7),
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent deliveries of the same event: the winner has already
        # committed the dedup record and the reconciliation. Do not disguise
        # any other integrity failure (for example a missing foreign key) as
        # a duplicate.
        db.rollback()
        if idempotency_repo.get_record(WEBHOOK_SYSTEM_MERCHANT_ID, webhook_key) is None:
            raise
        return {
            "status": "duplicate",
            "message": "Webhook event was previously processed and reconciled.",
            "event_id": event_id,
            "event_type": event_type,
        }

    return {
        "status": "processed",
        "event_id": event_id,
        "event_type": event_type,
        "message": "PayPal webhook event verified, deduplicated, and reconciled successfully.",
    }
