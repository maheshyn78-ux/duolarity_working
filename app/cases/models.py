import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, String, Text
from app.db.types import JSONB, UUID, UTCDateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class CaseStatus(StrEnum):
    DRAFT = "Draft"
    PENDING = "Pending"
    UNDER_REVIEW = "Under Review"
    VERIFIED = "Verified"
    REJECTED = "Rejected"
    CLOSED = "Closed"


class Case(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "cases"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )
    company_name: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    case_number: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(220))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default=CaseStatus.DRAFT.value, index=True)
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    assigned_organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )

    assignments: Mapped[list["CaseAssignment"]] = relationship(cascade="all, delete-orphan")


class CaseAssignment(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "case_assignments"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    assigned_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))


class CaseActivity(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "case_activities"

    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
