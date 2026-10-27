import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin
from app.db.types import JSONB, UUID


class Workspace(UUIDMixin, TimestampMixin, Base):
    """A client workspace shown in the sidebar."""

    __tablename__ = "workspaces"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    client_name: Mapped[str] = mapped_column(String(180))
    company: Mapped[str] = mapped_column(String(180), default="")
    industry: Mapped[str] = mapped_column(String(80), default="")


class Statement(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "statements"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"), index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workspaces.id"), nullable=True, index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(120), default="")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    file_hash: Mapped[str] = mapped_column(String(128), default="", index=True)
    storage_key: Mapped[str] = mapped_column(String(500), default="")

    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)  # queued|processing|completed|failed
    stage: Mapped[str] = mapped_column(String(80), default="Queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    pages_total: Mapped[int] = mapped_column(Integer, default=0)
    pages_done: Mapped[int] = mapped_column(Integer, default=0)
    method: Mapped[str] = mapped_column(String(40), default="")  # rules | table | llm | hybrid
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    bank_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_holder: Mapped[str | None] = mapped_column(String(180), nullable=True)
    account_number: Mapped[str | None] = mapped_column(String(60), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="INR")
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    closing_balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    txn_count: Mapped[int] = mapped_column(Integer, default=0)
    total_debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    total_credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    flagged_count: Mapped[int] = mapped_column(Integer, default=0)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class Transaction(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "transactions"

    statement_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("statements.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    txn_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    debit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    credit: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    balance: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    category: Mapped[str] = mapped_column(String(80), default="Uncategorized", index=True)
    ledger_head: Mapped[str] = mapped_column(String(80), default="Uncategorized")
    category_source: Mapped[str] = mapped_column(String(20), default="rule")  # rule | ai | manual
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
