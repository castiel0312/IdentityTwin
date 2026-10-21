from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.step_up import StepUpChallenge


class StepUpRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, challenge: StepUpChallenge) -> StepUpChallenge:
        self.db.add(challenge)
        self.db.commit()
        self.db.refresh(challenge)
        return challenge

    def get_by_id(self, challenge_id: UUID) -> StepUpChallenge | None:
        stmt = select(StepUpChallenge).where(StepUpChallenge.id == challenge_id)
        return self.db.scalars(stmt).first()

    def mark_verified(self, challenge: StepUpChallenge) -> StepUpChallenge:
        challenge.verified_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(challenge)
        return challenge

    def mark_used(self, challenge: StepUpChallenge) -> StepUpChallenge:
        challenge.used_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(challenge)
        return challenge
