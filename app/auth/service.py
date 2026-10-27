from datetime import timedelta
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import PasswordResetToken, RefreshToken, Role, User, UserRole
from app.auth.schemas import UserRead
from app.core.config import get_settings
from app.core.permissions import Permission, ROLE_PERMISSIONS, RoleName
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    utcnow,
    verify_password,
)


def get_user_roles(db: Session, user_id: UUID) -> list[str]:
    stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id).where(UserRole.user_id == user_id)
    return list(db.scalars(stmt).all())


def get_permissions_for_roles(role_names: list[str]) -> list[str]:
    permissions: set[Permission] = set()
    for role_name in role_names:
        try:
            permissions.update(ROLE_PERMISSIONS[RoleName(role_name)])
        except ValueError:
            continue
    return sorted(permission.value for permission in permissions)


def serialize_user(db: Session, user: User) -> UserRead:
    roles = get_user_roles(db, user.id)
    return UserRead(
        id=user.id,
        organization_id=user.organization_id,
        department_id=user.department_id,
        email=user.email,
        full_name=user.full_name,
        status=user.status,
        roles=roles,
        permissions=get_permissions_for_roles(roles),
    )


def authenticate_user(db: Session, email: str, password: str) -> User:
    user = db.scalar(select(User).where(User.email == email.lower()))
    if not user or not verify_password(password, user.password_hash) or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    user.last_login_at = utcnow()
    return user


def issue_token_pair(db: Session, user: User) -> tuple[str, str]:
    settings = get_settings()
    role_names = get_user_roles(db, user.id)
    access_token = create_access_token(
        user.id,
        {"organization_id": str(user.organization_id) if user.organization_id else None, "roles": role_names},
    )
    refresh_token = generate_opaque_token()
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_token),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_expire_days),
        )
    )
    return access_token, refresh_token


def rotate_refresh_token(db: Session, token: str) -> tuple[str, str]:
    stored = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_token(token)))
    if not stored or stored.revoked_at or stored.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    user = db.get(User, stored.user_id)
    if not user or user.status != "active":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")
    stored.revoked_at = utcnow()
    return issue_token_pair(db, user)


def create_password_reset_token(db: Session, user: User) -> str:
    settings = get_settings()
    raw_token = generate_opaque_token()
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=utcnow() + timedelta(minutes=settings.password_reset_token_expire_minutes),
        )
    )
    return raw_token


def reset_password(db: Session, token: str, new_password: str) -> None:
    stored = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_token(token)))
    if not stored or stored.used_at or stored.expires_at <= utcnow():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")
    user = db.get(User, stored.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid reset token")
    user.password_hash = hash_password(new_password)
    stored.used_at = utcnow()
