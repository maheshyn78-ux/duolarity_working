import uuid
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from app.db.types import JSONB, UUID, UTCDateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDMixin


class Document(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "documents"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True, index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=True, index=True)
    uploaded_by_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(220), index=True)
    category: Mapped[str] = mapped_column(String(80), default="uncategorized", index=True)
    status: Mapped[str] = mapped_column(String(40), default="uploaded", index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    files: Mapped[list["DocumentFile"]] = relationship(cascade="all, delete-orphan")


class DocumentFile(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_files"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120))
    size_bytes: Mapped[int] = mapped_column(Integer)
    file_hash: Mapped[str] = mapped_column(String(128), index=True)
    storage_key: Mapped[str] = mapped_column(String(500), unique=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)


class DocumentMetadata(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "document_metadata"

    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"), index=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
