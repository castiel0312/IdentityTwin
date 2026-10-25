import hashlib
import random
import threading
import uuid
from copy import deepcopy
from typing import Any

from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.models.evidence import (
    HoneyActivityLog,
    HoneyApiCredential,
    HoneyBalance,
    HoneyCustomer,
    HoneyInvoice,
    HoneyMerchantProfile,
    HoneyPayee,
    HoneyPayout,
    HoneyTransaction,
    HoneyWorkspaceState,
)

_WORLD_LOCK = threading.RLock()
_RESOURCE_TABLES = {
    "merchant": (HoneyMerchantProfile, lambda world: [("profile", world["merchant"])]),
    "balance": (HoneyBalance, lambda world: [("balance", world["balance"])]),
    "customers": (HoneyCustomer, lambda world: [(item["id"], item) for item in world["customers"]]),
    "invoices": (HoneyInvoice, lambda world: [(item["id"], item) for item in world["invoices"]]),
    "transactions": (
        HoneyTransaction,
        lambda world: [(item["id"], item) for item in world["transactions"]],
    ),
    "payouts": (
        HoneyPayout,
        lambda world: [(item["payout_batch_id"], item) for item in world["payouts"]],
    ),
    "payees": (HoneyPayee, lambda world: [(item["id"], item) for item in world["payees"]]),
    "api_credentials": (
        HoneyApiCredential,
        lambda world: [(item["client_id"], item) for item in world["api_credentials"]],
    ),
    "activity_log": (
        HoneyActivityLog,
        lambda world: [
            (str(item.get("id", index)), item) for index, item in enumerate(world["activity_log"])
        ],
    ),
}


def _seed_for_session(session_id: str) -> int:
    h = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def bootstrap(
    session_id: str, identity_id: str, intent_profile: dict[str, Any] | None = None
) -> dict[str, Any]:
    seed = _seed_for_session(session_id)
    rng = random.Random(seed)
    merchant_name = f"Sharma Enterprises {rng.randint(100, 999)}"
    balance = round(rng.uniform(150000, 850000), 2)
    customers = []
    for i in range(rng.randint(40, 80)):
        customers.append(
            {
                "id": f"CUST-{i:04d}",
                "name": f"Customer {i}",
                "email": f"customer{i}@example.in",
                "phone": f"+91{rng.randint(7000000000, 9999999999)}",
            }
        )
    invoices = []
    for i in range(rng.randint(30, 60)):
        invoices.append(
            {
                "id": f"INV-{i:05d}",
                "amount": round(rng.uniform(500, 25000), 2),
                "currency": "INR",
                "status": rng.choice(["PAID", "SENT", "PENDING"]),
                "date": "2026-10-01",
            }
        )
    transactions = []
    for i in range(rng.randint(60, 120)):
        transactions.append(
            {
                "id": f"TXN-{i:06d}",
                "amount": round(rng.uniform(-50000, 50000), 2),
                "currency": "INR",
                "type": rng.choice(["SALE", "PAYOUT", "REFUND"]),
                "date": "2026-09-15",
            }
        )
    payees = []
    for i in range(rng.randint(3, 8)):
        payees.append(
            {
                "id": f"PAYEE-{i:04d}",
                "email": f"vendor{i}@supplier.in",
                "name": f"Vendor {i}",
            }
        )
    api_apps = []
    for i in range(rng.randint(1, 2)):
        api_apps.append(
            {
                "client_id": f"AYS{rng.randint(100000000000000000, 999999999999999999)}",
                "name": f"App {i}",
            }
        )
    return {
        "session_id": session_id,
        "identity_id": identity_id,
        "merchant": {"name": merchant_name, "country": "IN"},
        "balance": {"amount": balance, "currency": "INR"},
        "customers": customers,
        "invoices": invoices,
        "transactions": transactions,
        "payees": payees,
        "api_credentials": api_apps,
        "activity_log": [],
        "payouts": [],
        "idempotency": {},
    }


def get_or_create_world(
    db: Session,
    session_id: str,
    identity_id: str,
    intent_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load a persisted synthetic world, creating its deterministic seed once."""
    with _WORLD_LOCK:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(123456789, 43)"))

        state = db.get(HoneyWorkspaceState, session_id)
        if state is not None:
            if state.identity_id != identity_id:
                raise ValueError("Honey workspace session is already bound to another identity.")
            profile = db.get(HoneyMerchantProfile, (session_id, identity_id, "profile"))
            if profile is None:
                _write_resource_records(db, session_id, identity_id, state.world)
                db.commit()
            return deepcopy(state.world)

        world = bootstrap(session_id, identity_id, intent_profile)
        db.add(
            HoneyWorkspaceState(
                session_id=session_id,
                identity_id=identity_id,
                synthetic=True,
                world=world,
            )
        )
        _write_resource_records(db, session_id, identity_id, world)
        db.commit()
        return deepcopy(world)


def save_world(db: Session, session_id: str, identity_id: str, world: dict[str, Any]) -> None:
    with _WORLD_LOCK:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(123456789, 43)"))
        state = db.get(HoneyWorkspaceState, session_id)
        if state is None or state.identity_id != identity_id:
            raise ValueError("Honey workspace session is not bound to this identity.")
        state.world = deepcopy(world)
        _write_resource_records(db, session_id, identity_id, world)
        db.commit()


def append_activity(
    db: Session,
    session_id: str,
    identity_id: str,
    method: str,
    path: str,
    occurred_at: str,
) -> None:
    with _WORLD_LOCK:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SELECT pg_advisory_xact_lock(123456789, 43)"))
        state = db.get(HoneyWorkspaceState, session_id)
        if state is None or state.identity_id != identity_id:
            raise ValueError("Honey workspace session is not bound to this identity.")
        event = {
            "id": uuid.uuid4().hex,
            "method": method,
            "path": path,
            "occurred_at": occurred_at,
            "synthetic": True,
        }
        world = deepcopy(state.world)
        world["activity_log"].append(event)
        state.world = world
        db.add(
            HoneyActivityLog(
                session_id=session_id,
                identity_id=identity_id,
                resource_id=event["id"],
                synthetic=True,
                data=event,
            )
        )
        db.commit()


def _write_resource_records(
    db: Session, session_id: str, identity_id: str, world: dict[str, Any]
) -> None:
    for model, records_for_world in _RESOURCE_TABLES.values():
        db.execute(delete(model).where(model.session_id == session_id))
        rows = [
            model(
                session_id=session_id,
                identity_id=identity_id,
                resource_id=str(resource_id),
                synthetic=True,
                data=deepcopy(data),
            )
            for resource_id, data in records_for_world(world)
        ]
        db.add_all(rows)
