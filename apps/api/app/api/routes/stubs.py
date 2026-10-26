from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.security import AuthenticatedPrincipal, get_current_principal
from app.db.session import get_db
from app.schemas.stubs import StandardErrorResponse

router = APIRouter()


@router.get(
    "/stream",
    response_model=StandardErrorResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses={501: {"model": StandardErrorResponse}},
    tags=["Real-Time Streaming (Person 2 - Risk & Person 5 - Evidence)"],
    summary="Real-time event and telemetry stream (SSE / WebSocket)",
    description="Live behavioral event stream stub. To be implemented by Person 2 and Person 5.",
)
def get_telemetry_stream() -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": "Real-time telemetry stream is not yet implemented.",
                "details": {
                    "owner": "Person 2 (Risk Intelligence) & Person 5 (Evidence Integrity)",
                    "planned_protocol": "Server-Sent Events (SSE) / WebSocket",
                },
            }
        },
    )


@router.post(
    "/signatures/{id}/approve",
    response_model=StandardErrorResponse,
    status_code=status.HTTP_501_NOT_IMPLEMENTED,
    responses={501: {"model": StandardErrorResponse}},
    tags=["Evidence Signatures (Person 5 - Evidence Integrity)"],
    summary="Approve cryptographic signature on evidence bundle",
    description="Cryptographic signature verification and evidence sign-off stub. To be implemented by Person 5.",
)
def approve_signature(id: UUID) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        content={
            "error": {
                "code": "NOT_IMPLEMENTED",
                "message": f"Signature approval for evidence bundle '{id}' is not yet implemented.",
                "details": {
                    "owner": "Person 5 (Evidence Integrity & Notarization)",
                    "signature_id": str(id),
                },
            }
        },
    )


@router.post(
    "/simulate/attack",
    tags=["Attack Simulation (Person 4 - Honey Workspace & Red Team)"],
    summary="Trigger simulated adversarial account-takeover attack scenario",
    description="Red-team simulation and honey-workspace drill trigger.",
)
def simulate_attack(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> dict:
    import uuid
    from datetime import datetime, timezone

    from app.core.config import settings
    from app.core.exceptions import PolicyViolationException
    from app.evidence.hashchain import EvidenceChain
    from app.honey.bootstrap import bootstrap
    from app.honey.canary import CanaryRegistryService
    from app.honey.containment import contain_canary_hit
    from app.models.principal import Merchant, User
    from app.models.session import SessionRecord
    from app.schemas.sessions import SessionStatus, TrustLevel

    if settings.ENVIRONMENT.lower() == "production":
        raise PolicyViolationException(
            message=(
                "Attack simulation is disabled in production. Use a designated "
                "non-production environment."
            ),
            code="SIMULATION_DISABLED_IN_PRODUCTION",
        )

    chain = EvidenceChain(db)
    session_id = str(uuid.uuid4())
    identity_id = str(uuid.uuid4())
    merchant_id = str(principal.merchant_id)
    user_id = str(principal.user_id)
    merchant_uuid = uuid.UUID(merchant_id)
    user_uuid = uuid.UUID(user_id)
    if db.get(Merchant, merchant_uuid) is None:
        db.add(
            Merchant(
                merchant_id=merchant_uuid,
                name="IdentityTwin Demo Merchant",
                slug=f"demo-{uuid.uuid4().hex[:12]}",
            )
        )
    if db.get(User, user_uuid) is None:
        db.add(
            User(
                user_id=user_uuid,
                merchant_id=merchant_uuid,
                email=f"{user_id}@simulation.invalid",
                role="merchant",
            )
        )
    session = SessionRecord(
        session_id=uuid.UUID(session_id),
        user_id=user_uuid,
        merchant_id=merchant_uuid,
        trust_level=TrustLevel.NORMAL.value,
        risk_score=0.0,
        status=SessionStatus.ACTIVE.value,
        last_activity_at=datetime.now(timezone.utc),
        device_fingerprint="sha256:synthetic-demo-device",
        ip_address="203.0.113.42",
    )
    db.add(session)
    db.commit()

    bootstrap(session_id, identity_id)
    chain.append(
        "login",
        {
            "type": "login",
            "session_id": session_id,
            "plane": "real",
            "device": "Delhi Windows/Chrome",
            "ip": "203.0.113.42",
        },
    )
    chain.append(
        "payee_add",
        {"type": "payee_add", "session_id": session_id, "plane": "real", "payee": "PAYEE-992"},
    )
    chain.append(
        "payout",
        {
            "type": "payout",
            "session_id": session_id,
            "plane": "real",
            "amount": 480000,
            "currency": "INR",
        },
    )
    # Route to honey
    reg = CanaryRegistryService(db)
    issued = reg.issue(session_id, identity_id, merchant_id)
    canary = issued[0]
    chain.append("honey_view", {"type": "honey_view", "session_id": session_id, "plane": "honey"})
    hit = reg.check(
        {
            "body": {"client_secret": canary["secret_value"]},
            "session_id": session_id,
            "matched_in": "developer.credentials.reveal",
        }
    )
    if not hit:
        raise RuntimeError("The simulated canary did not trigger.")
    incident_id = contain_canary_hit(db, hit)
    if incident_id is None:
        raise RuntimeError("The simulation could not isolate its session.")
    verify_res = chain.verify()
    return {
        "status": "ok",
        "session_id": session_id,
        "incident_sealed": True,
        "incident_id": incident_id,
        "evidence_verify": verify_res,
    }
