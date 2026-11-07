import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import OwnershipMismatchException
from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db, get_honey_db
from app.honey.bootstrap import append_activity, get_or_create_world, save_world
from app.honey.canary import CanaryRegistryService
from app.honey.containment import contain_canary_hit
from app.honey.evidence import append_honey_evidence
from app.honey.payouts import IdempotencyConflictError, create_synthetic_payout
from app.models.session import SessionRecord
from app.schemas.sessions import SessionStatus

# Maximum request body size to inspect for canaries (1 MB)
MAX_CANARY_INSPECTION_SIZE = 1024 * 1024


async def check_canary_request(
    request: Request,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
) -> None:
    # Read and cache the request body so downstream handlers can still access it
    body_bytes = await request.body()
    # Store in request._body so subsequent request.body() calls return the cached value
    request._body = body_bytes

    # Enforce maximum inspection size to prevent DoS
    if len(body_bytes) > MAX_CANARY_INSPECTION_SIZE:
        # For oversized bodies, we still allow the request to proceed but log the event
        # The body is still cached for downstream handlers
        body_for_inspection = body_bytes[:MAX_CANARY_INSPECTION_SIZE]
        # Log oversized body event for monitoring
        oversized_payload = {
            "type": "canary_inspection_oversized",
            "content_length": len(body_bytes),
            "max_inspection_size": MAX_CANARY_INSPECTION_SIZE,
            "path": request.url.path,
            "session_id": request.query_params.get("session_id"),
            "merchant_id": str(principal.merchant_id),
        }
        # Use a separate DB session or fire-and-forget for logging to avoid blocking
        # For now, append to evidence chain
        try:
            from app.evidence.hashchain import EvidenceChain
            EvidenceChain(db).append("canary_inspection_oversized", oversized_payload)
        except Exception:
            pass
    else:
        body_for_inspection = body_bytes

    try:
        body = json.loads(body_for_inspection) if body_for_inspection else {}
    except json.JSONDecodeError:
        # For non-JSON bodies, decode as text for string extraction
        # Limit to the inspection size (already bounded)
        body = body_for_inspection.decode("utf-8", errors="replace")

    session_id = request.query_params.get("session_id")
    if isinstance(body, dict):
        session_id = body.get("session_id") or session_id
    identity_id = request.query_params.get("identity_id")
    if isinstance(body, dict):
        identity_id = body.get("identity_id") or identity_id

    session_uuid = None
    if session_id is not None:
        try:
            session_uuid = UUID(str(session_id))
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=422, detail="session_id must be a valid UUID."
            ) from None
        owned_session = db.scalars(
            select(SessionRecord).where(
                SessionRecord.session_id == session_uuid,
                SessionRecord.merchant_id == principal.merchant_id,
                SessionRecord.user_id == principal.user_id,
            )
        ).first()
        if owned_session is None:
            raise OwnershipMismatchException(
                message="Session does not belong to the authenticated principal."
            )
        if owned_session.status != SessionStatus.ACTIVE.value:
            raise HTTPException(status_code=403, detail="Session is not active.")
        if identity_id is not None:
            try:
                requested_identity = UUID(str(identity_id))
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=422, detail="identity_id must be a valid UUID."
                ) from None
            if requested_identity != principal.user_id:
                raise OwnershipMismatchException(
                    message="Identity does not belong to the authenticated principal."
                )
        session_id = str(session_uuid)

    observation = {
        "headers": dict(request.headers),
        "path": request.url.path,
        "query": request.url.query,
        "body": body,
        "session_id": session_id,
        "identity_id": str(principal.user_id),
        "merchant_id": str(principal.merchant_id),
        "matched_in": request.url.path,
    }
    hit = CanaryRegistryService(db).check(observation, principal)
    if hit:
        hit["incident_id"] = contain_canary_hit(db, hit, principal)
        raise HTTPException(status_code=403, detail="This request was blocked.")

    if isinstance(session_id, str) and isinstance(identity_id, str):
        try:
            get_or_create_world(honey_db, session_id, str(principal.user_id))
            append_activity(
                honey_db,
                session_id,
                str(principal.user_id),
                request.method,
                request.url.path,
                datetime.now(timezone.utc).isoformat(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
    request.state.canary_hit = hit


router = APIRouter(
    prefix="/honey",
    tags=["Honey Workspace"],
    dependencies=[Depends(check_canary_request)],
)
provider_router = APIRouter(
    tags=["Synthetic Payment Provider"],
    dependencies=[Depends(check_canary_request)],
)


@provider_router.get("/v1/merchant/merchant-info")
@router.get("/merchant/profile")
def get_profile(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db, "honey_view", {"type": "honey_view", "session_id": session_id, "resource": "profile"}
    )
    return {"merchant": world["merchant"], "balance": world["balance"]}


@router.get("/customers")
def list_customers(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "customers.list"},
    )
    return {"items": world["customers"], "total": len(world["customers"])}


@router.get("/customers/{customer_id}")
def get_customer(
    customer_id: str,
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    customer = next((item for item in world["customers"] if item["id"] == customer_id), None)
    if customer is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    append_honey_evidence(
        db,
        "honey_action",
        {
            "type": "honey_action",
            "session_id": session_id,
            "resource": "customers.detail",
        },
    )
    return customer


@provider_router.get("/v2/invoicing/invoices")
@router.get("/invoices")
def list_invoices(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "invoices.list"},
    )
    return {"items": world["invoices"], "total": len(world["invoices"])}


@router.get("/invoices/export")
def export_invoices(
    session_id: str,
    identity_id: str,
    format: str = "csv",
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    reg = CanaryRegistryService(db)
    issued = reg.issue(session_id, identity_id, str(principal.merchant_id))
    canary = next((item for item in issued if item["kind"] == "invoice_export"), None)
    append_honey_evidence(
        db,
        "honey_action",
        {
            "type": "honey_action",
            "session_id": session_id,
            "resource": "invoices.export",
            "canary_tag": canary["tag"] if canary else None,
        },
    )
    exported = [
        {
            "invoice_id": invoice["id"],
            "amount": invoice["amount"],
            "currency": invoice["currency"],
            "status": invoice["status"],
            "reference": canary["tag"] if canary else "",
        }
        for invoice in world["invoices"][:5]
    ]
    if format.lower() == "json":
        return {"format": "json", "items": exported}
    if format.lower() != "csv":
        raise HTTPException(status_code=422, detail="Unsupported export format.")
    content = "invoice_id,amount,currency,status,reference\n"
    content += "".join(
        f"{invoice['invoice_id']},{invoice['amount']},{invoice['currency']},"
        f"{invoice['status']},{invoice['reference']}\n"
        for invoice in exported
    )
    return {"format": "csv", "content": content}


@provider_router.get("/v2/invoicing/invoices/{invoice_id}")
@router.get("/invoices/{invoice_id}")
def get_invoice(
    invoice_id: str,
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    invoice = next((item for item in world["invoices"] if item["id"] == invoice_id), None)
    if invoice is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "invoices.detail"},
    )
    return invoice


@provider_router.get("/v1/reporting/transactions")
@router.get("/transactions")
def list_transactions(
    session_id: str,
    identity_id: str,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    if page < 1 or not 1 <= page_size <= 100:
        raise HTTPException(status_code=422, detail="Invalid pagination values.")
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "transactions.list"},
    )
    start = (page - 1) * page_size
    items = world["transactions"][start : start + page_size]
    return {"items": items, "total": len(world["transactions"]), "page": page}


@router.get("/payees")
def list_payees(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "payees.list"},
    )
    return {"items": world["payees"], "total": len(world["payees"])}


@router.post("/payees")
async def add_payee(
    request: Request,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    session_id = body.get("session_id") or request.query_params.get("session_id")
    identity_id = body.get("identity_id") or request.query_params.get("identity_id")
    name = body.get("name")
    email = body.get("email")
    if not all(
        isinstance(value, str) and value.strip() for value in (session_id, identity_id, name, email)
    ):
        raise HTTPException(
            status_code=422, detail="session_id, identity_id, name and email are required."
        )
    world = get_or_create_world(honey_db, session_id, identity_id)
    payee = {
        "id": f"PAYEE-{uuid.uuid4().hex[:8].upper()}",
        "name": name[:128],
        "email": email[:254],
    }
    world["payees"].append(payee)
    save_world(honey_db, session_id, identity_id, world)
    append_honey_evidence(
        db,
        "payee_add",
        {
            "type": "payee_add",
            "session_id": session_id,
            "plane": "honey",
            "payee": payee["id"],
        },
    )
    return payee


@provider_router.get("/v1/payments/payouts")
@router.get("/payouts")
def list_payouts(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "payouts.list"},
    )
    return {"items": world["payouts"], "total": len(world["payouts"])}


@provider_router.get("/v1/payments/payouts/{payout_batch_id}")
@router.get("/payouts/{payout_batch_id}")
def get_payout(
    payout_batch_id: str,
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    payout = next(
        (item for item in world["payouts"] if item["payout_batch_id"] == payout_batch_id),
        None,
    )
    if payout is None:
        raise HTTPException(status_code=404, detail="Resource not found.")
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "payouts.detail"},
    )
    return payout


@provider_router.post("/v1/payments/payouts")
@router.post("/payouts")
async def create_payout(
    request: Request,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Expected a JSON object.")
    session_id = body.get("session_id") or request.query_params.get("session_id")
    identity_id = body.get("identity_id") or request.query_params.get("identity_id")
    amount = body.get("amount", 0)
    recipient = body.get("recipient_email") or body.get("receiver")
    if not session_id or not identity_id:
        raise HTTPException(status_code=422, detail="session_id and identity_id are required.")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="amount must be a positive number.") from None
    if not 0 < amount < float("inf"):
        raise HTTPException(status_code=422, detail="amount must be a positive finite number.")

    idempotency_key = request.headers.get("PayPal-Request-Id") or request.headers.get(
        "Idempotency-Key"
    )
    idempotency_key = idempotency_key[:128] if idempotency_key else None
    try:
        return create_synthetic_payout(
            db,
            honey_db,
            session_id=str(session_id),
            identity_id=str(identity_id),
            amount=amount,
            currency=str(body.get("currency") or "INR").upper(),
            recipient=str(recipient) if recipient is not None else None,
            idempotency_key=idempotency_key,
        )
    except IdempotencyConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/developer/apps")
def list_apps(
    session_id: str,
    identity_id: str,
    db: Session = Depends(get_db),
    honey_db: Session = Depends(get_honey_db),
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    world = get_or_create_world(honey_db, session_id, identity_id)
    reg = CanaryRegistryService(db)
    reg.issue(session_id, identity_id, str(principal.merchant_id))
    apps = []
    for app in world["api_credentials"]:
        apps.append(
            {
                "client_id": app["client_id"],
                "name": app["name"],
                "client_secret": "HIDDEN",
            }
        )
    append_honey_evidence(
        db,
        "honey_action",
        {"type": "honey_action", "session_id": session_id, "resource": "developer.apps"},
    )
    return {"items": apps}


@router.post("/developer/credentials/reveal")
async def reveal_creds(request: Request, db: Session = Depends(get_db)):
    body = await request.json()
    _ = body.get("client_secret") or body.get("secret")  # Consumed for canary detection via middleware
    hit = getattr(request.state, "canary_hit", None)
    if hit:
        # Canary was already detected by middleware and would have raised 403
        # This path should not be reached, but handle defensively
        return {"revealed": False, "error": "Canary interaction detected"}
    # For non-canary secrets, acknowledge without echoing the secret
    append_honey_evidence(
        db,
        "honey_action",
        {
            "type": "honey_action",
            "session_id": body.get("session_id") or request.query_params.get("session_id"),
            "resource": "developer.credentials.reveal",
        },
    )
    return {"revealed": True}


@router.post("/developer/token")
async def issue_access_token(request: Request):
    body = await request.json()
    if not isinstance(body, dict) or not body.get("client_id") or not body.get("client_secret"):
        raise HTTPException(status_code=401, detail="Invalid client credentials.")
    return {
        "access_token": uuid.uuid4().hex + uuid.uuid4().hex,
        "token_type": "Bearer",
        "expires_in": 28800,
        "scope": "openid",
    }
