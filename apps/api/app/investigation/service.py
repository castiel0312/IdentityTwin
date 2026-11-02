"""Read-only AI Investigator service.

Hard boundaries enforced here:

* reads deterministic, merchant-scoped evidence only;
* never writes risk decisions, trust levels, sessions, payouts or gateway state;
* never calls the risk engine, gateway or payment provider;
* every recommendation is advisory and requires human approval;
* LLM failure always falls back to the deterministic narrative.
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
from app.db.repositories.investigation_repo import InvestigationRepository
from app.investigation.extraction import (
    ExtractedEvidence,
    as_utc,
    compact_evidence,
    ensure_incident_access,
    extract_evidence,
    safe_text,
)
from app.investigation.llm import generate_llm_narrative
from app.models.investigation import InvestigationRecord
from app.schemas.investigations import (
    EvidenceReference,
    InvestigationBundle,
    InvestigationCreateRequest,
    InvestigationFinding,
    InvestigationFindingType,
    InvestigationListResponse,
    InvestigationNarrative,
    InvestigationRecommendation,
    InvestigationResponse,
    InvestigationStatus,
)

_SIGNAL_FINDINGS = {
    "NEW_DEVICE": InvestigationFindingType.NEW_DEVICE,
    "NEW_LOCATION": InvestigationFindingType.NEW_LOCATION,
    "UNUSUAL_TIME": InvestigationFindingType.UNUSUAL_TIME,
    "NEW_PAYEE": InvestigationFindingType.NEW_PAYEE,
    "LARGE_PAYOUT": InvestigationFindingType.LARGE_PAYOUT,
    "NEW_PAYEE_LARGE_PAYOUT": InvestigationFindingType.NEW_PAYEE_LARGE_PAYOUT,
    "PAYEE_ADD_THEN_PAYOUT": InvestigationFindingType.PAYEE_ADD_THEN_PAYOUT,
    "CANARY_INTERACTION": InvestigationFindingType.CANARY_INTERACTION,
}

_LIMITATIONS = [
    "The Investigator is read-only and advisory. It cannot route, score, isolate, approve or pay.",
    "Only redacted deterministic evidence from the authenticated merchant scope is used.",
    "Absence of a recorded signal is not proof that activity was benign.",
    "Evidence verification is consistency evidence, not immutable custody.",
    "Recommendations require human approval and never change enforcement policy automatically.",
]


def _severity_for_score(score: float) -> str:
    if score >= 90:
        return "CRITICAL"
    if score >= 60:
        return "HIGH"
    if score >= 30:
        return "MEDIUM"
    return "LOW"


def _decision_refs(evidence: ExtractedEvidence) -> list[EvidenceReference]:
    refs: list[EvidenceReference] = []
    for decision in evidence.decisions[-10:]:
        refs.append(
            EvidenceReference(
                source="risk_decision",
                ref_id=str(decision.decision_id),
                summary=(
                    f"score={decision.risk_score:.1f}, trust={decision.trust_level}, "
                    f"action={decision.action}, destination={decision.routing_destination}"
                ),
                occurred_at=as_utc(decision.evaluated_at),
            )
        )
    return refs


def _build_findings(
    evidence: ExtractedEvidence,
) -> list[InvestigationFinding]:
    findings: list[InvestigationFinding] = []
    seen: set[tuple[str, str]] = set()
    incident = evidence.incident

    canary_payloads = [
        (entry, payload)
        for entry, payload in evidence.chain_entries
        if payload.get("type") == "canary_triggered"
    ]
    if (
        incident.trigger_reason == "CANARY_INTERACTION"
        or canary_payloads
        or any(canary.triggered_at is not None for canary in evidence.canaries)
    ):
        refs = [
            EvidenceReference(
                source="evidence_chain",
                ref_id=entry.event_ref,
                summary="Canary interaction recorded in the evidence chain.",
                occurred_at=as_utc(entry.created_at),
                evidence_seq=entry.seq,
                evidence_hash=entry.hash,
            )
            for entry, _ in canary_payloads[:5]
        ]
        findings.append(
            InvestigationFinding(
                finding_id="canary-interaction",
                finding_type=InvestigationFindingType.CANARY_INTERACTION,
                title="Synthetic canary resource was accessed",
                severity="CRITICAL",
                explanation=(
                    "A uniquely tagged honey resource was observed in this session. "
                    "Canary access is a strong indicator of unauthorized use; the "
                    "deterministic gateway already owns containment."
                ),
                evidence=refs
                or [
                    EvidenceReference(
                        source="incident",
                        ref_id=str(incident.incident_id),
                        summary="Incident trigger reason is CANARY_INTERACTION.",
                        occurred_at=as_utc(incident.created_at),
                    )
                ],
            )
        )
        seen.add(("canary", str(incident.incident_id)))

    for decision in evidence.decisions:
        signals = {
            str(name).upper(): float(points)
            for name, points in (decision.risk_signals or {}).items()
            if isinstance(points, (int, float))
        }
        for name, points in sorted(signals.items()):
            finding_type = _SIGNAL_FINDINGS.get(name)
            if finding_type is None or points <= 0:
                continue
            key = (finding_type.value, str(decision.decision_id))
            if key in seen:
                continue
            seen.add(key)
            findings.append(
                InvestigationFinding(
                    finding_id=f"{finding_type.value.lower()}-{decision.decision_id}",
                    finding_type=finding_type,
                    title=name.replace("_", " ").title(),
                    severity=_severity_for_score(decision.risk_score),
                    explanation=(
                        f"Risk decision {decision.decision_id} recorded {name} "
                        f"contributing {points:.1f} points, producing score "
                        f"{decision.risk_score:.1f} and trust level {decision.trust_level}. "
                        "This explanation does not replace the authoritative decision."
                    ),
                    evidence=[
                        EvidenceReference(
                            source="risk_decision",
                            ref_id=str(decision.decision_id),
                            summary=f"{name} +{points:.1f} points",
                            occurred_at=as_utc(decision.evaluated_at),
                        )
                    ],
                )
            )

    isolated_payouts = [
        payout
        for payout in evidence.payouts
        if payout.status in {"blocked", "isolated", "session_isolated"}
    ]
    if isolated_payouts or (evidence.session and evidence.session.trust_level == "ISOLATED"):
        findings.append(
            InvestigationFinding(
                finding_id="blocked-payout",
                finding_type=InvestigationFindingType.BLOCKED_PAYOUT,
                title="Payment activity was blocked or isolated",
                severity="CRITICAL",
                explanation=(
                    "The deterministic gateway recorded a blocked/isolated payment "
                    "outcome. No provider execution is assumed for these records."
                ),
                evidence=[
                    EvidenceReference(
                        source="payout",
                        ref_id=str(payout.payout_id),
                        summary=f"status={payout.status}, amount={payout.amount} {payout.currency}",
                        occurred_at=as_utc(payout.created_at),
                    )
                    for payout in isolated_payouts[:5]
                ],
            )
        )

    decoy_payouts = [
        payout
        for payout in evidence.payouts
        if payout.status in {"decoy", "decoy_forward", "honey"} or payout.provider_name == "honey"
    ]
    if decoy_payouts or (evidence.session and evidence.session.trust_level == "DECOY"):
        findings.append(
            InvestigationFinding(
                finding_id="decoy-containment",
                finding_type=InvestigationFindingType.DECOY_CONTAINMENT,
                title="Session was routed to synthetic containment",
                severity="HIGH",
                explanation=(
                    "A decoy/honey destination was recorded. Synthetic honey activity "
                    "must never be reconciled with the real payout ledger."
                ),
                evidence=[
                    EvidenceReference(
                        source="payout",
                        ref_id=str(payout.payout_id),
                        summary=f"provider={payout.provider_name}, status={payout.status}",
                        occurred_at=as_utc(payout.created_at),
                    )
                    for payout in decoy_payouts[:5]
                ],
            )
        )

    if evidence.session is not None and evidence.session.status == "revoked":
        findings.append(
            InvestigationFinding(
                finding_id="session-revoked",
                finding_type=InvestigationFindingType.SESSION_REVOKED,
                title="Session is recorded as revoked",
                severity="HIGH",
                explanation=(
                    "The session is no longer active. This report does not restore it; "
                    "only an authorized human workflow can decide whether to do so."
                ),
                evidence=[
                    EvidenceReference(
                        source="session",
                        ref_id=str(evidence.session.session_id),
                        summary=f"status={evidence.session.status}",
                        occurred_at=as_utc(evidence.session.updated_at),
                    )
                ],
            )
        )

    if not findings:
        findings.append(
            InvestigationFinding(
                finding_id="no-material-signal",
                finding_type=InvestigationFindingType.HIGH_RISK_DECISION,
                title="No material anomaly recorded in extracted evidence",
                severity="LOW",
                explanation=(
                    "No named deterministic risk signal, containment event or canary "
                    "interaction was found in the bounded evidence window. This does "
                    "not prove the activity was benign."
                ),
                evidence=[
                    EvidenceReference(
                        source="incident",
                        ref_id=str(incident.incident_id),
                        summary=f"trigger={incident.trigger_reason}, score={incident.risk_score:.1f}",
                        occurred_at=as_utc(incident.created_at),
                    )
                ],
            )
        )

    return findings


def _build_recommendations(
    findings: list[InvestigationFinding],
) -> list[InvestigationRecommendation]:
    types = {finding.finding_type for finding in findings}
    recommendations = [
        InvestigationRecommendation(
            action="Preserve the current containment and trust state.",
            rationale=(
                "The Trust Gateway remains authoritative. This investigation is a "
                "read-only projection and must not be used to re-enable a session or "
                "replay a payout."
            ),
            priority="HIGH",
        ),
        InvestigationRecommendation(
            action="Review the deterministic risk ledger and evidence seal.",
            rationale=(
                "Support every conclusion with the recorded risk decision and sealed "
                "evidence range before taking any operational action."
            ),
            priority="MEDIUM",
        ),
        InvestigationRecommendation(
            action="Escalate to a human analyst for any enforcement change.",
            rationale=(
                "No policy, access or payment decision is changed automatically by this report."
            ),
            priority="HIGH",
        ),
    ]
    if InvestigationFindingType.CANARY_INTERACTION in types:
        recommendations.insert(
            0,
            InvestigationRecommendation(
                action="Rotate credentials and review any resource exposed to this session.",
                rationale=(
                    "Canary access suggests synthetic or real credentials may have been "
                    "observed. Rotation requires explicit human approval."
                ),
                priority="CRITICAL",
            ),
        )
    if InvestigationFindingType.BLOCKED_PAYOUT in types:
        recommendations.insert(
            0,
            InvestigationRecommendation(
                action="Confirm no provider execution occurred for blocked payouts.",
                rationale=(
                    "Blocked/isolated records must be reconciled against the provider "
                    "ledger by a human; do not retry them automatically."
                ),
                priority="CRITICAL",
            ),
        )
    if InvestigationFindingType.DECOY_CONTAINMENT in types:
        recommendations.append(
            InvestigationRecommendation(
                action="Keep synthetic honey activity isolated from the real ledger.",
                rationale="Decoy records are deception data and must not be reconciled as real payments.",
                priority="HIGH",
            )
        )
    return recommendations


def _deterministic_narrative(
    evidence: ExtractedEvidence, findings: list[InvestigationFinding]
) -> InvestigationNarrative:
    incident = evidence.incident
    top = sorted(
        findings,
        key=lambda finding: {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}.get(
            finding.severity, 4
        ),
    )
    headline = f"{incident.title}: {top[0].title}" if top else incident.title
    summary = (
        f"Incident {incident.incident_id} is {incident.status} with recorded risk "
        f"score {incident.risk_score:.1f} and trigger {incident.trigger_reason}. "
        f"The bounded evidence window contains {len(evidence.decisions)} risk "
        f"decision(s), {len(evidence.payouts)} payout record(s), "
        f"{len(evidence.events)} event(s) and {len(evidence.chain_entries)} evidence "
        f"chain entr{'y' if len(evidence.chain_entries) == 1 else 'ies'}."
    )
    why = " ".join(finding.explanation for finding in top[:4]).strip()
    notes = [
        "This narrative is derived only from redacted, recorded deterministic evidence.",
        "A provisional behavioral twin may attenuate novelty signals; treat it as uncertainty.",
    ]
    if evidence.seal is None:
        notes.append("No evidence seal was found for this incident in the extracted scope.")
    return InvestigationNarrative(
        headline=safe_text(headline, limit=200),
        summary=safe_text(summary, limit=2000),
        why_suspicious=safe_text(why, limit=2000) or "No material suspicion was established.",
        uncertainty_notes=notes,
        generated_by="deterministic",
    )


def _build_evidence_refs(evidence: ExtractedEvidence) -> list[EvidenceReference]:
    refs: list[EvidenceReference] = [
        EvidenceReference(
            source="incident",
            ref_id=str(evidence.incident.incident_id),
            summary=(
                f"trigger={evidence.incident.trigger_reason}, "
                f"severity={evidence.incident.severity}, "
                f"score={evidence.incident.risk_score:.1f}"
            ),
            occurred_at=as_utc(evidence.incident.created_at),
        )
    ]
    if evidence.session is not None:
        refs.append(
            EvidenceReference(
                source="session",
                ref_id=str(evidence.session.session_id),
                summary=(
                    f"status={evidence.session.status}, trust={evidence.session.trust_level}, "
                    f"score={evidence.session.risk_score:.1f}"
                ),
                occurred_at=as_utc(evidence.session.last_activity_at),
            )
        )
    refs.extend(_decision_refs(evidence))
    refs.extend(
        EvidenceReference(
            source="payout",
            ref_id=str(payout.payout_id),
            summary=(
                f"amount={payout.amount} {payout.currency}, status={payout.status}, "
                f"provider={payout.provider_name}"
            ),
            occurred_at=as_utc(payout.created_at),
        )
        for payout in evidence.payouts[-10:]
    )
    refs.extend(
        EvidenceReference(
            source="evidence_chain",
            ref_id=safe_text(payload.get("type") or entry.event_ref, limit=64),
            summary=f"Evidence chain entry seq {entry.seq}.",
            occurred_at=as_utc(entry.created_at),
            evidence_seq=entry.seq,
            evidence_hash=entry.hash,
        )
        for entry, payload in evidence.chain_entries[-20:]
    )
    if evidence.seal is not None:
        refs.append(
            EvidenceReference(
                source="evidence_chain",
                ref_id=str(evidence.seal.seal_id),
                summary=(
                    f"Sealed evidence range {evidence.seal.start_seq}-{evidence.seal.end_seq}."
                ),
                occurred_at=as_utc(evidence.seal.sealed_at),
                evidence_seq=evidence.seal.end_seq,
                evidence_hash=evidence.seal.head_hash,
            )
        )
    for canary in evidence.canaries:
        refs.append(
            EvidenceReference(
                source="canary",
                ref_id=str(canary.canary_id),
                summary=f"kind={canary.kind}, armed={canary.armed}",
                occurred_at=as_utc(canary.triggered_at),
            )
        )
    return refs


class InvestigationService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = InvestigationRepository(db)

    def create(
        self,
        incident_id: UUID,
        request: InvestigationCreateRequest,
        principal: AuthenticatedPrincipal,
    ) -> InvestigationResponse:
        if not settings.AI_INVESTIGATION_ENABLED:
            raise PolicyViolationException(
                message="AI Investigator is disabled in this deployment.",
                code="AI_INVESTIGATION_DISABLED",
            )
        if principal.role not in (RoleEnum.ANALYST, RoleEnum.ADMIN):
            raise InsufficientPermissionsException(
                message="AI Investigator runs require analyst or admin credentials.",
                code="ANALYST_ROLE_REQUIRED",
            )

        evidence = extract_evidence(
            self.db,
            principal,
            incident_id,
            max_events=settings.AI_INVESTIGATION_MAX_EVENTS,
        )
        findings = _build_findings(evidence)
        narrative = _deterministic_narrative(evidence, findings)
        llm_requested = request.use_llm and settings.AI_LLM_ENABLED
        projection = compact_evidence(evidence)
        llm_narrative = generate_llm_narrative(
            projection.payload,
            requested=llm_requested and projection.redaction_applied,
        )
        if llm_narrative is not None:
            narrative = llm_narrative

        bundle = InvestigationBundle(
            incident_id=evidence.incident.incident_id,
            session_id=evidence.incident.session_id,
            merchant_id=evidence.incident.merchant_id,
            focus=safe_text(request.focus, limit=200) or None,
            risk_score=evidence.incident.risk_score,
            trust_level=(
                evidence.session.trust_level if evidence.session else "UNKNOWN"
            ),
            trigger_reason=evidence.incident.trigger_reason,
            incident_status=evidence.incident.status,
            evidence_counts={
                "events": len(evidence.events),
                "risk_decisions": len(evidence.decisions),
                "payouts": len(evidence.payouts),
                "evidence_chain_entries": len(evidence.chain_entries),
                "canaries": len(evidence.canaries),
            },
            findings=findings,
            evidence=_build_evidence_refs(evidence),
            recommendations=_build_recommendations(findings),
            narrative=narrative,
            redaction_applied=projection.redaction_applied,
            ai_used=llm_narrative is not None,
            model_name=settings.AI_LLM_MODEL if llm_narrative is not None else None,
            limitations=_LIMITATIONS,
        )
        status = (
            InvestigationStatus.FALLBACK if llm_requested and llm_narrative is None
            else InvestigationStatus.COMPLETE
        )
        record = self.repo.create(
            InvestigationRecord(
                merchant_id=principal.merchant_id,
                incident_id=evidence.incident.incident_id,
                session_id=evidence.incident.session_id,
                created_by=principal.user_id,
                status=status.value,
                ai_used=bundle.ai_used,
                model_name=bundle.model_name,
                bundle=bundle.model_dump(mode="json"),
            )
        )
        # Transaction ownership stays in the service. Extraction is read-only, so
        # committing here only persists the single investigation record.
        self.db.commit()
        self.db.refresh(record)
        return self._to_response(record)

    def list_for_incident(
        self,
        incident_id: UUID,
        principal: AuthenticatedPrincipal,
        *,
        page: int = 1,
        page_size: int = 25,
    ) -> InvestigationListResponse:
        # Tenant check only: listing investigations must never read the chain.
        ensure_incident_access(self.db, principal, incident_id)
        items, total = self.repo.list_for_incident(
            principal.merchant_id,
            incident_id,
            limit=page_size,
            offset=(page - 1) * page_size,
        )
        return InvestigationListResponse(
            items=[self._to_response(item) for item in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    def get(
        self, investigation_id: UUID, principal: AuthenticatedPrincipal
    ) -> InvestigationResponse:
        record = self.repo.get(investigation_id, principal.merchant_id)
        if record is None:
            raise EntityNotFoundException(
                message="Investigation not found.", code="INVESTIGATION_NOT_FOUND"
            )
        return self._to_response(record)

    @staticmethod
    def _to_response(record: InvestigationRecord) -> InvestigationResponse:
        return InvestigationResponse(
            investigation_id=record.investigation_id,
            incident_id=record.incident_id,
            session_id=record.session_id,
            merchant_id=record.merchant_id,
            status=InvestigationStatus(record.status),
            ai_used=record.ai_used,
            model_name=record.model_name,
            created_by=record.created_by,
            created_at=record.created_at,
            updated_at=record.updated_at,
            bundle=InvestigationBundle.model_validate(record.bundle),
        )
