from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.exceptions import (
    EntityNotFoundException,
    InsufficientPermissionsException,
    OwnershipMismatchException,
    PolicyViolationException,
)
from app.core.security import AuthenticatedPrincipal, RoleEnum
from app.db.repositories.incident_repo import IncidentRepository
from app.models.evidence import IncidentSeal
from app.models.incident import IncidentRecord
from app.schemas.evidence import EvidenceSealSummary
from app.schemas.incidents import (
    IncidentActionAvailability,
    IncidentActionRequest,
    IncidentActionResponse,
    IncidentActionsResponse,
    IncidentResponse,
    IncidentSealResponse,
    IncidentStatus,
)


class IncidentService:
    def __init__(self, db: Session):
        self.db = db
        self.incident_repo = IncidentRepository(db)

    def list_incidents(
        self,
        principal: AuthenticatedPrincipal,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        q: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[IncidentResponse], int]:
        # Merchants can only see their own incidents
        # Analysts can see incidents in their merchant scope
        merchant_filter = principal.merchant_id
        items, total = self.incident_repo.list(
            merchant_id=merchant_filter,
            status=status,
            severity=severity,
            limit=limit,
            offset=offset,
            q=q,
            start=start,
            end=end,
            sort=sort,
        )
        responses = [IncidentResponse.model_validate(item) for item in items]
        return responses, total

    def get_incident(
        self,
        incident_id: UUID,
        principal: AuthenticatedPrincipal,
    ) -> IncidentResponse:
        incident = self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise EntityNotFoundException(
                message=f"Incident '{incident_id}' not found.",
                code="INCIDENT_NOT_FOUND",
            )

        # Validate merchant scope
        if incident.merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Access denied: Incident belongs to a different merchant domain.",
                code="INCIDENT_SCOPE_MISMATCH",
            )

        return IncidentResponse.model_validate(incident)

    def approve_incident(
        self,
        incident_id: UUID,
        request: IncidentActionRequest,
        principal: AuthenticatedPrincipal,
    ) -> IncidentActionResponse:
        # 1. Enforce analyst role
        if principal.role != RoleEnum.ANALYST and principal.role != RoleEnum.ADMIN:
            raise InsufficientPermissionsException(
                message="Incident approval requires analyst role credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

        # 2. Retrieve incident & validate merchant scope
        incident = self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise EntityNotFoundException(
                message=f"Incident '{incident_id}' not found.",
                code="INCIDENT_NOT_FOUND",
            )

        if incident.merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Access denied: Cannot approve incidents outside authorized merchant scope.",
                code="MERCHANT_SCOPE_VIOLATION",
            )

        # Invariant: Cannot approve already resolved or rejected incidents without reopening
        if incident.status in (IncidentStatus.RESOLVED.value, IncidentStatus.REJECTED.value):
            raise PolicyViolationException(
                message=f"Cannot approve incident in terminal '{incident.status}' state.",
                code="TERMINAL_STATE_ERROR",
            )

        previous_status = IncidentStatus(incident.status)

        # 3. CRITICAL INVARIANT:
        # An approval must NOT automatically execute a payout, override a trust decision, or disable isolation.
        # It only logs the analyst action and updates incident review status.
        updated_incident = self.incident_repo.record_action(
            incident=incident,
            new_status=IncidentStatus.APPROVED.value,
            analyst_id=principal.user_id,
            action_type="approved",
            notes=request.notes,
            metadata={"resolution_reason": request.resolution_reason},
        )

        return IncidentActionResponse(
            incident_id=updated_incident.incident_id,
            action="approved",
            previous_status=previous_status,
            new_status=IncidentStatus.APPROVED,
            analyst_id=principal.user_id,
            timestamp=updated_incident.updated_at,
            notes=request.notes,
            message="Incident review approved. Audit trail updated.",
        )

    def resolve_incident(
        self,
        incident_id: UUID,
        request: IncidentActionRequest,
        principal: AuthenticatedPrincipal,
    ) -> IncidentActionResponse:
        # Enforce analyst role
        if principal.role != RoleEnum.ANALYST and principal.role != RoleEnum.ADMIN:
            raise InsufficientPermissionsException(
                message="Incident resolution requires analyst role credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

        incident = self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise EntityNotFoundException(
                message=f"Incident '{incident_id}' not found.",
                code="INCIDENT_NOT_FOUND",
            )

        if incident.merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Access denied: Cannot resolve incidents outside authorized merchant scope.",
                code="MERCHANT_SCOPE_VIOLATION",
            )

        previous_status = IncidentStatus(incident.status)

        updated_incident = self.incident_repo.record_action(
            incident=incident,
            new_status=IncidentStatus.RESOLVED.value,
            analyst_id=principal.user_id,
            action_type="resolved",
            notes=request.notes,
            metadata={"resolution_reason": request.resolution_reason},
        )

        return IncidentActionResponse(
            incident_id=updated_incident.incident_id,
            action="resolved",
            previous_status=previous_status,
            new_status=IncidentStatus.RESOLVED,
            analyst_id=principal.user_id,
            timestamp=updated_incident.updated_at,
            notes=request.notes,
            message="Incident resolved and archived.",
        )

    def approve_revocation(
        self,
        incident_id: UUID,
        request: IncidentActionRequest,
        principal: AuthenticatedPrincipal,
    ) -> IncidentActionResponse:
        # 1. Enforce analyst / admin role
        if principal.role != RoleEnum.ANALYST and principal.role != RoleEnum.ADMIN:
            raise InsufficientPermissionsException(
                message="Incident revocation approval requires analyst or admin credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

        # 2. Retrieve incident & validate merchant scope
        incident = self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise EntityNotFoundException(
                message=f"Incident '{incident_id}' not found.",
                code="INCIDENT_NOT_FOUND",
            )

        if incident.merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Access denied: Cannot approve incidents outside authorized merchant scope.",
                code="MERCHANT_SCOPE_VIOLATION",
            )

        previous_status = IncidentStatus(incident.status)

        # 3. CRITICAL INVARIANTS:
        # - Records analyst audit action confirming the session revocation.
        # - NEVER re-enables a session or executes a payout.
        updated_incident = self.incident_repo.record_action(
            incident=incident,
            new_status=IncidentStatus.RESOLVED.value,
            analyst_id=principal.user_id,
            action_type="approved_revocation",
            notes=request.notes,
            metadata={
                "resolution_reason": request.resolution_reason or "SESSION_REVOCATION_CONFIRMED",
                "revocation_approved": True,
            },
        )

        # Explicitly ensure associated session remains revoked if present
        if incident.session_id:
            from app.db.repositories.session_repo import SessionRepository
            from app.schemas.sessions import SessionStatus

            s_repo = SessionRepository(self.db)
            session = s_repo.get_by_id(incident.session_id)
            if session:
                session.status = SessionStatus.REVOKED.value
                self.db.commit()

        return IncidentActionResponse(
            incident_id=updated_incident.incident_id,
            action="approved_revocation",
            previous_status=previous_status,
            new_status=IncidentStatus.RESOLVED,
            analyst_id=principal.user_id,
            timestamp=updated_incident.updated_at,
            notes=request.notes,
            message="Incident revocation confirmed and approved. Session remains revoked. No payout executed.",
        )

    def get_actions(
        self, incident_id: UUID, principal: AuthenticatedPrincipal
    ) -> IncidentActionsResponse:
        incident = self._scoped_incident(incident_id, principal)
        is_analyst = principal.role in (RoleEnum.ANALYST, RoleEnum.ADMIN)
        terminal = incident.status in (
            IncidentStatus.RESOLVED.value,
            IncidentStatus.REJECTED.value,
        )
        actions = [
            IncidentActionAvailability(
                action="approve",
                label="Approve review",
                allowed=is_analyst and incident.status != IncidentStatus.RESOLVED.value,
                required_roles=["analyst", "admin"],
                reason=(
                    None
                    if is_analyst and incident.status != IncidentStatus.RESOLVED.value
                    else (
                        "Analyst or admin role is required."
                        if not is_analyst
                        else "A resolved incident cannot be approved."
                    )
                ),
            ),
            IncidentActionAvailability(
                action="resolve",
                label="Resolve and archive",
                allowed=is_analyst and not terminal,
                required_roles=["analyst", "admin"],
                reason=(
                    None
                    if is_analyst and not terminal
                    else (
                        "Analyst or admin role is required."
                        if not is_analyst
                        else "Incident is already in a terminal state."
                    )
                ),
                destructive=True,
            ),
            IncidentActionAvailability(
                action="approve-revocation",
                label="Confirm session revocation",
                allowed=is_analyst and incident.session_id is not None and not terminal,
                required_roles=["analyst", "admin"],
                reason=(
                    None
                    if is_analyst and incident.session_id is not None and not terminal
                    else (
                        "Analyst or admin role is required."
                        if not is_analyst
                        else (
                            "Incident has no associated session."
                            if incident.session_id is None
                            else "Incident is already in a terminal state."
                        )
                    )
                ),
                destructive=True,
            ),
        ]
        return IncidentActionsResponse(
            incident_id=incident.incident_id,
            current_status=IncidentStatus(incident.status),
            principal_role=principal.role.value,
            actions=actions,
        )

    def get_seal(
        self, incident_id: UUID, principal: AuthenticatedPrincipal
    ) -> IncidentSealResponse:
        incident = self._scoped_incident(incident_id, principal)
        seal = (
            self.db.query(IncidentSeal)
            .filter(IncidentSeal.incident_id == incident.incident_id)
            .order_by(IncidentSeal.sealed_at.desc())
            .first()
        )
        if seal is None:
            return IncidentSealResponse(
                incident_id=incident.incident_id, sealed=False, seal=None
            )
        return IncidentSealResponse(
            incident_id=incident.incident_id,
            sealed=True,
            seal=EvidenceSealSummary(
                seal_id=seal.seal_id,
                incident_id=seal.incident_id,
                incident_title=incident.title,
                incident_status=incident.status,
                session_id=seal.session_id,
                merchant_id=seal.merchant_id,
                start_seq=seal.start_seq,
                end_seq=seal.end_seq,
                head_hash=seal.head_hash,
                sealed_at=seal.sealed_at,
            ),
        )

    def _scoped_incident(
        self, incident_id: UUID, principal: AuthenticatedPrincipal
    ) -> IncidentRecord:
        incident = self.incident_repo.get_by_id(incident_id)
        if not incident:
            raise EntityNotFoundException(
                message=f"Incident '{incident_id}' not found.",
                code="INCIDENT_NOT_FOUND",
            )
        if incident.merchant_id != principal.merchant_id:
            raise OwnershipMismatchException(
                message="Access denied: Incident belongs to a different merchant domain.",
                code="INCIDENT_SCOPE_MISMATCH",
            )
        return incident
