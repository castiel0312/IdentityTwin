import uuid
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from app.models.session import SessionRecord

from sqlalchemy import Boolean, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Merchant(Base, TimestampMixin):
    __tablename__ = "merchants"

    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    users: Mapped[list["User"]] = relationship("User", back_populates="merchant")
    sessions: Mapped[list["SessionRecord"]] = relationship(
        "SessionRecord", back_populates="merchant"
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    merchant_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("merchants.merchant_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="merchant", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    merchant: Mapped["Merchant"] = relationship("Merchant", back_populates="users")
    sessions: Mapped[list["SessionRecord"]] = relationship("SessionRecord", back_populates="user")
