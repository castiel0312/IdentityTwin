"""Read-only operator projections for the synthetic honey workspace.

Deliberately separate from the attacker-facing `/v1/honey/*` routes: no canary
secret value is ever projected, no synthetic resource is created, no payment is
executed and no containment check is triggered by an operator reading this data.
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.exceptions import EntityNotFoundException
from app.core.security import AuthenticatedPrincipal
from app.models.canary import CanaryRecord
from app.models.evidence import HoneyWorkspaceState
from app.models.incident import IncidentRecord
from app.models.session import SessionRecord
from app.schemas.honey_operator import (
    HoneyActivityView,
    HoneyBalanceView,
    HoneyCanaryListResponse,
    HoneyCanaryView,
    HoneyMerchantView,
    HoneyPayeeView,
    HoneyPayoutView,
    HoneyTransactionView,
    HoneyWorkspaceDetailResponse,
    HoneyWorkspaceListResponse,
    HoneyWorkspaceSummary,
)


def _uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _accessible_session_ids(db: Session, principal: AuthenticatedPrincipal) -> set[UUID]:
    session_ids = set(
        db.scalars(
            select(SessionRecord.session_id).where(
                SessionRecord.merchant_id == principal.merchant_id
            )
        ).all()
    )
    session_ids.update(
        session_id
        for session_id in db.scalars(
            select(CanaryRecord.session_id).where(
                CanaryRecord.merchant_id == principal.merchant_id,
                CanaryRecord.session_id.is_not(None),
            )
        ).all()
        if session_id is not None
    )
    return session_ids


def _canaries_for_merchant(
    db: Session, principal: AuthenticatedPrincipal, session_ids: set[UUID]
) -> list[CanaryRecord]:
    filters = [CanaryRecord.merchant_id == principal.merchant_id]
    if session_ids:
        filters.append(CanaryRecord.session_id.in_(session_ids))
    return list(
        db.scalars(
            select(CanaryRecord)
            .where(or_(*filters))
            .order_by(CanaryRecord.created_at.desc())
        ).all()
    )


def _canaries_for_sessions(
    db: Session, session_ids: set[UUID]
) -> list[CanaryRecord]:
    if not session_ids:
        return []
    return list(
        db.scalars(
            select(CanaryRecord)
            .where(CanaryRecord.session_id.in_(session_ids))
            .order_by(CanaryRecord.created_at.desc())
        ).all()
    )


def _incident_map(
    db: Session, principal: AuthenticatedPrincipal, session_ids: set[UUID]
) -> dict[UUID, IncidentRecord]:
    if not session_ids:
        return {}
    incidents = list(
        db.scalars(
            select(IncidentRecord)
            .where(
                IncidentRecord.merchant_id == principal.merchant_id,
                IncidentRecord.session_id.in_(session_ids),
            )
            .order_by(IncidentRecord.created_at.desc())
        ).all()
    )
    mapping: dict[UUID, IncidentRecord] = {}
    for incident in incidents:
        if incident.session_id is not None and incident.session_id not in mapping:
            mapping[incident.session_id] = incident
    return mapping


def _canary_view(
    canary: CanaryRecord, incidents: dict[UUID, IncidentRecord]
) -> HoneyCanaryView:
    incident = incidents.get(canary.session_id) if canary.session_id else None
    return HoneyCanaryView(
        canary_id=canary.canary_id,
        session_id=canary.session_id,
        identity_id=canary.identity_id,
        kind=canary.kind,
        tag=canary.tag,
        armed=canary.armed,
        triggered_at=_as_utc(canary.triggered_at),
        containment_incident_id=incident.incident_id if incident else None,
        containment_status=incident.status if incident else None,
    )


def _summary(
    db: Session,
    state: HoneyWorkspaceState,
    session: SessionRecord,
    canaries: list[CanaryRecord],
    incidents: dict[UUID, IncidentRecord],
) -> HoneyWorkspaceSummary:
    world = state.world or {}
    merchant = world.get("merchant") or {}
    balance = world.get("balance") or {}
    canary_list = [
        canary
        for canary in canaries
        if canary.session_id is not None and str(canary.session_id) == state.session_id
    ]
    incident = incidents.get(session.session_id)
    return HoneyWorkspaceSummary(
        session_id=session.session_id,
        identity_id=_uuid_or_none(state.identity_id),
        synthetic=True,
        merchant_name=str(merchant.get("name") or "Synthetic Merchant"),
        merchant_country=merchant.get("country"),
        balance=HoneyBalanceView(
            amount=float(balance.get("amount") or 0.0),
            currency=str(balance.get("currency") or "INR"),
        ),
        payee_count=len(world.get("payees") or []),
        transaction_count=len(world.get("transactions") or []),
        payout_count=len(world.get("payouts") or []),
        activity_count=len(world.get("activity_log") or []),
        canary_count=len(canary_list),
        canaries_triggered=sum(1 for canary in canary_list if canary.triggered_at),
        containment_incident_id=incident.incident_id if incident else None,
        session_status=session.status,
        updated_at=_as_utc(state.updated_at),
    )


def list_workspaces(
    db: Session,
    honey_db: Session,
    principal: AuthenticatedPrincipal,
    *,
    page: int = 1,
    page_size: int = 25,
) -> HoneyWorkspaceListResponse:
    session_ids = _accessible_session_ids(db, principal)
    if not session_ids:
        return HoneyWorkspaceListResponse(items=[], total=0, page=page, page_size=page_size)
    states = list(
        honey_db.scalars(
            select(HoneyWorkspaceState)
            .where(HoneyWorkspaceState.session_id.in_([str(value) for value in session_ids]))
            .order_by(HoneyWorkspaceState.updated_at.desc())
        ).all()
    )
    total = len(states)
    offset = (page - 1) * page_size
    states = states[offset : offset + page_size]
    canaries = _canaries_for_merchant(db, principal, session_ids)
    incidents = _incident_map(db, principal, session_ids)
    sessions = {
        session.session_id: session
        for session in db.scalars(
            select(SessionRecord).where(SessionRecord.session_id.in_(session_ids))
        ).all()
    }
    items = []
    for state in states:
        session = sessions.get(_uuid_or_none(state.session_id))
        if session is None:
            continue
        items.append(_summary(db, state, session, canaries, incidents))
    return HoneyWorkspaceListResponse(
        items=items, total=total, page=page, page_size=page_size
    )


def list_canaries(
    db: Session, principal: AuthenticatedPrincipal
) -> HoneyCanaryListResponse:
    session_ids = _accessible_session_ids(db, principal)
    canaries = _canaries_for_merchant(db, principal, session_ids)
    incidents = _incident_map(db, principal, session_ids)
    return HoneyCanaryListResponse(
        items=[_canary_view(canary, incidents) for canary in canaries],
        total=len(canaries),
    )


def get_workspace(
    db: Session,
    honey_db: Session,
    principal: AuthenticatedPrincipal,
    session_id: UUID,
) -> HoneyWorkspaceDetailResponse:
    session = db.get(SessionRecord, session_id)
    if session is None or session.merchant_id != principal.merchant_id:
        raise EntityNotFoundException(
            message="Synthetic workspace not found.",
            code="HONEY_WORKSPACE_NOT_FOUND",
        )
    state = honey_db.get(HoneyWorkspaceState, str(session_id))
    if state is None:
        raise EntityNotFoundException(
            message=(
                "No synthetic workspace has been provisioned for this session. "
                "The honey workspace is created only when a decoy interaction occurs."
            ),
            code="HONEY_WORKSPACE_NOT_PROVISIONED",
        )
    world = state.world or {}
    session_ids = {session_id}
    canaries = _canaries_for_sessions(db, session_ids)
    incidents = _incident_map(db, principal, session_ids)
    summary = _summary(db, state, session, canaries, incidents)

    merchant = world.get("merchant") or {}
    balance = world.get("balance") or {}
    payees = [
        HoneyPayeeView(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or ""),
            email=str(item.get("email") or ""),
        )
        for item in (world.get("payees") or [])
        if isinstance(item, dict)
    ]
    transactions = [
        HoneyTransactionView(
            id=str(item.get("id") or ""),
            amount=float(item.get("amount") or 0.0),
            currency=str(item.get("currency") or ""),
            type=str(item.get("type") or ""),
            date=item.get("date"),
        )
        for item in (world.get("transactions") or [])[:200]
        if isinstance(item, dict)
    ]
    payouts = [
        HoneyPayoutView(
            payout_batch_id=str(item.get("payout_batch_id") or ""),
            batch_status=str(item.get("batch_status") or ""),
            amount=float(item.get("amount") or 0.0),
            currency=str(item.get("currency") or ""),
            recipient=item.get("recipient"),
            transaction_id=item.get("transaction_id"),
        )
        for item in (world.get("payouts") or [])[:100]
        if isinstance(item, dict)
    ]
    recent_activity = [
        HoneyActivityView(
            id=str(item.get("id") or ""),
            method=str(item.get("method") or ""),
            path=str(item.get("path") or ""),
            occurred_at=str(item.get("occurred_at") or ""),
            synthetic=True,
        )
        for item in (world.get("activity_log") or [])[-100:]
        if isinstance(item, dict)
    ]

    notes = [
        "Every record on this page is synthetic. It is never merged with real merchant transactions.",
        "Canary secret values are excluded: exposing them would let an attacker forge a canary hit.",
        "The attacker-facing honey routes remain separate from this read-only operator projection.",
    ]
    incident = incidents.get(session_id)
    if incident is not None:
        notes.append(
            f"Containment incident {incident.incident_id} is {incident.status} "
            f"(trigger: {incident.trigger_reason})."
        )

    return HoneyWorkspaceDetailResponse(
        workspace=summary,
        merchant=HoneyMerchantView(
            name=str(merchant.get("name") or "Synthetic Merchant"),
            country=merchant.get("country"),
        ),
        balance=HoneyBalanceView(
            amount=float(balance.get("amount") or 0.0),
            currency=str(balance.get("currency") or "INR"),
        ),
        payees=payees,
        transactions=transactions,
        payouts=payouts,
        recent_activity=recent_activity,
        canaries=[_canary_view(canary, incidents) for canary in canaries],
        containment_notes=notes,
        raw_world_meta={
            "synthetic": True,
            "source": "honey.workspace_state",
            "identity_id": state.identity_id,
            "session_updated_at": state.updated_at.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
    )
