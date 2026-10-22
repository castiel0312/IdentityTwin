"""Persistence for behavioural twins and session risk ledgers."""

import uuid
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.twin import BehavioralTwin, SessionRiskStateRecord
from app.risk.schemas import (
    RiskContribution,
    SequenceMarker,
    SessionRiskState,
    TwinSnapshot,
)


class TwinRepository:
    """Repository for the Person 2 behavioural twin persistence layer."""

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    # Behavioural twins
    # ------------------------------------------------------------------
    def get_twin(self, merchant_id: UUID, user_id: UUID) -> BehavioralTwin | None:
        stmt = select(BehavioralTwin).where(
            BehavioralTwin.merchant_id == merchant_id,
            BehavioralTwin.user_id == user_id,
        )
        return self.db.scalars(stmt).first()

    def get_or_create_twin(self, merchant_id: UUID, user_id: UUID) -> BehavioralTwin:
        twin = self.get_twin(merchant_id, user_id)
        if twin:
            return twin
        twin = BehavioralTwin(
            twin_id=uuid.uuid4(),
            merchant_id=merchant_id,
            user_id=user_id,
            sample_count=0,
            confirmed_devices=[],
            confirmed_locations=[],
            payee_observations={},
            device_observations={},
            location_observations={},
            hour_histogram={},
            total_amount=0.0,
            amount_count=0,
        )
        self.db.add(twin)
        self.db.commit()
        self.db.refresh(twin)
        return twin

    def save_twin_snapshot(self, snapshot: TwinSnapshot) -> BehavioralTwin:
        twin = self.get_or_create_twin(snapshot.merchant_id, snapshot.user_id)
        twin.sample_count = snapshot.sample_count
        twin.confirmed_devices = list(snapshot.confirmed_devices)
        twin.confirmed_locations = list(snapshot.confirmed_locations)
        twin.payee_observations = dict(snapshot.payee_observations)
        twin.device_observations = dict(snapshot.device_observations)
        twin.location_observations = dict(snapshot.location_observations)
        twin.hour_histogram = {str(k): int(v) for k, v in snapshot.hour_histogram.items()}
        twin.total_amount = float(snapshot.total_amount)
        twin.amount_count = int(snapshot.amount_count)
        twin.last_updated_at = snapshot.last_updated_at or datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(twin)
        return twin

    @staticmethod
    def to_snapshot(record: BehavioralTwin) -> TwinSnapshot:
        histogram: dict[str, int] = {}
        for key, value in (record.hour_histogram or {}).items():
            try:
                histogram[str(key)] = int(value)
            except (TypeError, ValueError):
                continue
        return TwinSnapshot(
            merchant_id=record.merchant_id,
            user_id=record.user_id,
            sample_count=record.sample_count or 0,
            confirmed_devices=list(record.confirmed_devices or []),
            confirmed_locations=list(record.confirmed_locations or []),
            payee_observations={
                str(k): int(v) for k, v in (record.payee_observations or {}).items()
            },
            device_observations={
                str(k): int(v) for k, v in (record.device_observations or {}).items()
            },
            location_observations={
                str(k): int(v) for k, v in (record.location_observations or {}).items()
            },
            hour_histogram=histogram,
            total_amount=float(record.total_amount or 0.0),
            amount_count=int(record.amount_count or 0),
            last_updated_at=record.last_updated_at,
        )

    # ------------------------------------------------------------------
    # Session risk ledgers
    # ------------------------------------------------------------------
    def get_session_state(self, session_id: UUID) -> SessionRiskStateRecord | None:
        stmt = select(SessionRiskStateRecord).where(SessionRiskStateRecord.session_id == session_id)
        return self.db.scalars(stmt).first()

    def get_or_create_session_state(
        self, session_id: UUID, merchant_id: UUID, user_id: UUID
    ) -> SessionRiskStateRecord:
        record = self.get_session_state(session_id)
        if record:
            return record
        record = SessionRiskStateRecord(
            state_id=uuid.uuid4(),
            session_id=session_id,
            merchant_id=merchant_id,
            user_id=user_id,
            carried_forward=0.0,
            raw_points_sum=0.0,
            decay_points_total=0.0,
            current_score=0.0,
            canary_points=0.0,
            contributions=[],
            latched_signals=[],
            fired_payees=[],
            registered_payees=[],
            sequence_markers=[],
            consumed_markers=[],
            event_fingerprints=[],
            canary_seen=False,
        )
        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def save_session_state(self, state: SessionRiskState) -> SessionRiskStateRecord:
        record = self.get_or_create_session_state(
            state.session_id, state.merchant_id, state.user_id
        )
        record.carried_forward = float(state.carried_forward)
        record.raw_points_sum = float(state.raw_points_sum)
        record.decay_points_total = float(state.decay_points_total)
        record.current_score = float(state.current_score)
        record.canary_points = float(state.canary_points)
        record.contributions = [
            contribution.model_dump(mode="json") for contribution in state.contributions
        ]
        record.latched_signals = list(state.latched_signals)
        record.fired_payees = list(state.fired_payees)
        record.registered_payees = list(state.registered_payees)
        record.sequence_markers = [
            marker.model_dump(mode="json") for marker in state.sequence_markers
        ]
        record.consumed_markers = list(state.consumed_markers)
        record.event_fingerprints = list(state.event_fingerprints)
        record.canary_seen = bool(state.canary_seen)
        record.last_evaluated_at = state.updated_at or datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(record)
        return record

    @staticmethod
    def to_state(record: SessionRiskStateRecord) -> SessionRiskState:
        contributions: list[RiskContribution] = []
        for payload in record.contributions or []:
            try:
                contributions.append(RiskContribution.model_validate(payload))
            except Exception:  # noqa: BLE001 - corrupted ledger rows must not break evaluation
                continue
        markers: list[SequenceMarker] = []
        for payload in record.sequence_markers or []:
            try:
                markers.append(SequenceMarker.model_validate(payload))
            except Exception:  # noqa: BLE001 - corrupted ledger rows must not break evaluation
                continue
        return SessionRiskState(
            session_id=record.session_id,
            merchant_id=record.merchant_id,
            user_id=record.user_id,
            carried_forward=float(record.carried_forward or 0.0),
            raw_points_sum=float(record.raw_points_sum or 0.0),
            decay_points_total=float(record.decay_points_total or 0.0),
            current_score=float(record.current_score or 0.0),
            canary_points=float(record.canary_points or 0.0),
            contributions=contributions,
            latched_signals=list(record.latched_signals or []),
            fired_payees=list(record.fired_payees or []),
            registered_payees=list(record.registered_payees or []),
            sequence_markers=markers,
            consumed_markers=list(record.consumed_markers or []),
            event_fingerprints=list(record.event_fingerprints or []),
            canary_seen=bool(record.canary_seen),
            updated_at=record.last_evaluated_at,
        )
