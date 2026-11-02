"""Persistence and read service for advisory intent profiles.

Hard boundaries:

* every source read is scoped to the authenticated merchant and session;
* profiles are immutable snapshots and never feed risk scoring or enforcement;
* LLM output can replace prose only, never the deterministic analysis;
* provider failure always falls back to the deterministic narrative.
"""

from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    EntityNotFoundException,
    InsufficientPermissionsException,
    PolicyViolationException,
)
from app.core.security import AuthenticatedPrincipal, RoleEnum
from app.db.repositories.intent_repo import IntentProfileRepository
from app.intent.classifier import classify_intent
from app.intent.llm import generate_intent_llm_narrative
from app.intent.loader import ensure_session_access, load_intent_source
from app.intent.narrative import (
    build_intent_llm_projection,
    compact_analysis,
    deterministic_narrative,
)
from app.intent.signals import extract_intent_signals
from app.models.intent import IntentProfileRecord
from app.schemas.intent import (
    IntentExtractionPolicy,
    IntentProfileBundle,
    IntentProfileCreateRequest,
    IntentProfileListResponse,
    IntentProfileResponse,
    IntentProfileStatus,
)


class IntentProfileService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IntentProfileRepository(db)

    def create(
        self,
        session_id: UUID,
        request: IntentProfileCreateRequest,
        principal: AuthenticatedPrincipal,
    ) -> IntentProfileResponse:
        if not settings.INTENT_PROFILER_ENABLED:
            raise PolicyViolationException(
                message="Intent Profiler is disabled in this deployment.",
                code="INTENT_PROFILER_DISABLED",
            )
        if principal.role not in (RoleEnum.ANALYST, RoleEnum.ADMIN):
            raise InsufficientPermissionsException(
                message="Intent Profiler runs require analyst or admin credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

        policy = IntentExtractionPolicy()
        source = load_intent_source(
            self.db,
            principal,
            session_id,
            policy=policy,
        )
        analysis = compact_analysis(classify_intent(extract_intent_signals(source, policy)))
        narrative = deterministic_narrative(analysis)
        projection = build_intent_llm_projection(analysis)
        llm_requested = request.use_llm and settings.AI_LLM_ENABLED
        llm_narrative = generate_intent_llm_narrative(
            projection.payload,
            requested=llm_requested and projection.redaction_applied,
        )
        if llm_narrative is not None:
            narrative = llm_narrative

        bundle = IntentProfileBundle(
            session_id=source.session.session_id,
            merchant_id=principal.merchant_id,
            analysis=analysis,
            narrative=narrative,
            redaction_applied=projection.redaction_applied,
            ai_used=llm_narrative is not None,
            model_name=settings.AI_LLM_MODEL if llm_narrative is not None else None,
        )
        status = (
            IntentProfileStatus.FALLBACK
            if llm_requested and llm_narrative is None
            else IntentProfileStatus.COMPLETE
        )
        record = self.repo.create(
            IntentProfileRecord(
                merchant_id=principal.merchant_id,
                session_id=source.session.session_id,
                created_by=principal.user_id,
                status=status.value,
                ai_used=bundle.ai_used,
                model_name=bundle.model_name,
                bundle=bundle.model_dump(mode="json"),
            )
        )
        self.db.commit()
        self.db.refresh(record)
        return self._to_response(record)

    def list_for_session(
        self,
        session_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> IntentProfileListResponse:
        ensure_session_access(self.db, principal, session_id)
        items, total = self.repo.list_for_session(
            principal.merchant_id,
            session_id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return IntentProfileListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get(self, profile_id: UUID, principal: AuthenticatedPrincipal) -> IntentProfileResponse:
        record = self.repo.get(profile_id, principal.merchant_id)
        if record is None:
            raise EntityNotFoundException(
                message="Intent profile not found.", code="INTENT_PROFILE_NOT_FOUND"
            )
        return self._to_response(record)

    @staticmethod
    def _to_response(record: IntentProfileRecord) -> IntentProfileResponse:
        return IntentProfileResponse(
            profile_id=record.profile_id,
            session_id=record.session_id,
            merchant_id=record.merchant_id,
            status=IntentProfileStatus(record.status),
            ai_used=record.ai_used,
            model_name=record.model_name,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
            bundle=IntentProfileBundle.model_validate(record.bundle),
        )
