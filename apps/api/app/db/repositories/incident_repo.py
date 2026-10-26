from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.incident import AnalystActionRecord, IncidentRecord


class IncidentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, incident_id: UUID) -> IncidentRecord | None:
        stmt = select(IncidentRecord).where(IncidentRecord.incident_id == incident_id)
        return self.db.scalars(stmt).first()

    def list(
        self,
        merchant_id: UUID | None = None,
        status: str | None = None,
        severity: str | None = None,
        limit: int = 50,
        offset: int = 0,
        *,
        q: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        sort: str = "-created_at",
    ) -> tuple[list[IncidentRecord], int]:
        filters = []
        if merchant_id:
            filters.append(IncidentRecord.merchant_id == merchant_id)
        if status:
            filters.append(IncidentRecord.status == status)
        if severity:
            filters.append(IncidentRecord.severity == severity)
        if q:
            term = f"%{q.strip()}%"
            filters.append(
                or_(
                    IncidentRecord.title.ilike(term),
                    IncidentRecord.description.ilike(term),
                    IncidentRecord.trigger_reason.ilike(term),
                )
            )
        if start:
            filters.append(IncidentRecord.created_at >= start)
        if end:
            filters.append(IncidentRecord.created_at <= end)

        total_stmt = select(func.count()).select_from(IncidentRecord)
        if filters:
            total_stmt = total_stmt.where(*filters)
        total = self.db.scalar(total_stmt) or 0

        descending = sort.startswith("-")
        key = sort.lstrip("-")
        if key == "risk_score":
            column = IncidentRecord.risk_score
        elif key == "severity":
            column = IncidentRecord.severity
        elif key == "status":
            column = IncidentRecord.status
        else:
            column = IncidentRecord.created_at
        ordering = column.desc() if descending else column.asc()

        stmt = select(IncidentRecord)
        if filters:
            stmt = stmt.where(*filters)
        stmt = stmt.order_by(ordering).limit(limit).offset(offset)

        items = list(self.db.scalars(stmt).all())
        return items, total

    def create(self, incident: IncidentRecord) -> IncidentRecord:
        self.db.add(incident)
        self.db.commit()
        self.db.refresh(incident)
        return incident

    def record_action(
        self,
        incident: IncidentRecord,
        new_status: str,
        analyst_id: UUID,
        action_type: str,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> IncidentRecord:
        incident.status = new_status
        now = datetime.now(timezone.utc)
        incident.updated_at = now
        if new_status in ("RESOLVED", "APPROVED"):
            incident.resolved_at = now
            incident.resolved_by = analyst_id

        action = AnalystActionRecord(
            incident_id=incident.incident_id,
            analyst_id=analyst_id,
            action_type=action_type,
            notes=notes,
            action_metadata=metadata or {},
            performed_at=now,
        )
        self.db.add(action)
        self.db.commit()
        self.db.refresh(incident)
        return incident
