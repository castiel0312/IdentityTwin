import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.honey.bootstrap import get_or_create_world, save_world
from app.honey.evidence import append_honey_evidence


def create_synthetic_payout(
    db: Session,
    honey_db: Session,
    *,
    session_id: str,
    identity_id: str,
    amount: float,
    currency: str,
    recipient: str | None,
    idempotency_key: str | None,
    transaction_id_prefix: str = "TXN-",
) -> dict[str, Any]:
    world = get_or_create_world(honey_db, session_id, identity_id)
    if idempotency_key and idempotency_key in world["idempotency"]:
        return world["idempotency"][idempotency_key]["response"]

    payout_batch_id = f"BATCH-{uuid.uuid4().hex[:12].upper()}"
    transaction_id = f"{transaction_id_prefix}{uuid.uuid4().hex[:12].upper()}"
    sender_batch_id = f"SENDER-{uuid.uuid4().hex[:10].upper()}"
    balance = world["balance"]
    if currency == balance["currency"]:
        balance["amount"] = round(float(balance["amount"]) - amount, 2)

    payout = {
        "payout_batch_id": payout_batch_id,
        "batch_status": "SUCCESS",
        "amount": amount,
        "currency": currency,
        "recipient": recipient,
        "transaction_id": transaction_id,
    }
    world["payouts"].append(payout)
    world["transactions"].insert(
        0,
        {
            "id": transaction_id,
            "amount": -amount,
            "currency": currency,
            "type": "PAYOUT",
            "date": "2026-10-25",
        },
    )
    if recipient:
        recipient_text = str(recipient)[:254]
        if not any(payee["email"] == recipient_text for payee in world["payees"]):
            world["payees"].append(
                {
                    "id": f"PAYEE-{uuid.uuid4().hex[:8].upper()}",
                    "email": recipient_text,
                    "name": recipient_text,
                }
            )

    response = {
        "batch_header": {
            "payout_batch_id": payout_batch_id,
            "batch_status": "SUCCESS",
            "sender_batch_header": {"sender_batch_id": sender_batch_id},
        },
        "items": [
            {
                "transaction_id": transaction_id,
                "transaction_status": {"status": "SUCCESS"},
            }
        ],
        "links": [
            {
                "href": f"/v1/payments/payouts/{payout_batch_id}",
                "rel": "self",
                "method": "GET",
            }
        ],
        "balance": {"amount": balance["amount"], "currency": balance["currency"]},
    }
    if idempotency_key:
        world["idempotency"][idempotency_key] = {"response": response}

    append_honey_evidence(
        db,
        "honey_action",
        {
            "type": "honey_action",
            "session_id": session_id,
            "resource": "payouts.create",
            "amount": amount,
            "currency": currency,
            "recipient": recipient,
            "transaction_id": transaction_id,
        },
    )
    save_world(honey_db, session_id, identity_id, world)
    return response
