"""Portable column types so the app runs on PostgreSQL (Docker) and SQLite (zero-setup)."""
from datetime import timezone

from sqlalchemy import JSON, DateTime, TypeDecorator, Uuid
from sqlalchemy.dialects import postgresql

UUID = Uuid  # UUID(as_uuid=True) keeps working on both backends
JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")


class UTCDateTime(TypeDecorator):
    """Always returns timezone-aware UTC datetimes (SQLite drops tzinfo)."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
