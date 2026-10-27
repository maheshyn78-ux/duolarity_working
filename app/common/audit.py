from uuid import UUID

from sqlalchemy.orm import Session

from app.common.models import AuditLog


def write_audit_log(
    db: Session,
    *,
    action: str,
    actor_user_id: UUID | None = None,
    organization_id: UUID | None = None,
    target_type: str | None = None,
    target_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            action=action,
            actor_user_id=actor_user_id,
            organization_id=organization_id,
            target_type=target_type,
            target_id=target_id,
            metadata_json=metadata or {},
        )
    )
