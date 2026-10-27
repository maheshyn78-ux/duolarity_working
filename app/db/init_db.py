from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.auth.models import Role, User, UserRole
from app.common.audit import write_audit_log
from app.core.config import get_settings
from app.core.permissions import ROLE_PERMISSIONS
from app.core.security import hash_password


def validate_database_connection(db: Session) -> None:
    db.execute(text("SELECT 1"))


def seed_default_roles(db: Session) -> None:
    for role_name in ROLE_PERMISSIONS:
        role = db.scalar(select(Role).where(Role.name == role_name.value, Role.is_system.is_(True)))
        if not role:
            db.add(Role(name=role_name.value, description=f"Default {role_name.value} role", is_system=True))
    db.commit()


def seed_super_admin(db: Session) -> None:
    settings = get_settings()
    user = db.scalar(select(User).where(User.email == settings.seed_super_admin_email.lower()))
    role = db.scalar(select(Role).where(Role.name == "Super Admin", Role.is_system.is_(True)))
    if not role:
        return
    if not user:
        user = User(
            email=settings.seed_super_admin_email.lower(),
            full_name="System Administrator",
            password_hash=hash_password(settings.seed_super_admin_password),
            status="active",
            is_email_verified=True,
        )
        db.add(user)
        db.flush()
        write_audit_log(db, action="seed.super_admin_created", actor_user_id=user.id)
    if not db.scalar(select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)):
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.commit()


def initialize_database(db: Session) -> None:
    validate_database_connection(db)
    import app.db.models  # noqa: F401  (register all tables, incl. statements)
    from app.db.base import Base
    Base.metadata.create_all(bind=db.get_bind())  # idempotent; Alembic still manages Postgres in Docker
    seed_default_roles(db)
    seed_super_admin(db)
    from app.statements.models import Statement

    stale = db.scalars(select(Statement).where(Statement.status.in_(["queued", "processing"]))).all()
    for st in stale:
        st.status, st.stage, st.error = "failed", "Interrupted", "Server restarted during processing. Use Reprocess."
    db.commit()
