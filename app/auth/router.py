from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import get_current_user, require_permission
from app.auth.models import Role, User, UserRole, UserSettings
from app.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenPair,
    UserProfileUpdate,
    UserRead,
    UserSettingsRead,
    UserSettingsUpdate,
)
from app.auth.service import (
    authenticate_user,
    create_password_reset_token,
    get_permissions_for_roles,
    get_user_roles,
    issue_token_pair,
    reset_password,
    rotate_refresh_token,
    serialize_user,
)
from app.common.audit import write_audit_log
from app.core.config import get_settings
from app.core.permissions import Permission
from app.db.session import get_db

router = APIRouter(tags=["Authentication"])
users_router = APIRouter(prefix="/users", tags=["Users"])


@router.post("/auth/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenPair:
    user = authenticate_user(db, payload.email, payload.password)
    access_token, refresh_token = issue_token_pair(db, user)
    write_audit_log(db, action="auth.login", actor_user_id=user.id, organization_id=user.organization_id)
    db.commit()
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/auth/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenPair:
    from app.core.security import hash_password

    if not get_settings().allow_registration:
        raise HTTPException(status_code=403, detail="Registration is disabled")
    email = payload.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, full_name=payload.full_name.strip(), password_hash=hash_password(payload.password), status="active", is_email_verified=True)
    db.add(user)
    db.flush()
    role = db.scalar(select(Role).where(Role.name == "Analyst", Role.is_system.is_(True)))
    if role:
        db.add(UserRole(user_id=user.id, role_id=role.id))
    db.add(UserSettings(user_id=user.id))
    write_audit_log(db, action="auth.register", actor_user_id=user.id)
    db.commit()
    access_token, refresh_token = issue_token_pair(db, user)
    db.commit()
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/auth/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    access_token, refresh_token = rotate_refresh_token(db, payload.refresh_token)
    db.commit()
    return TokenPair(access_token=access_token, refresh_token=refresh_token)


@router.post("/auth/forgot-password", status_code=status.HTTP_202_ACCEPTED)
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    reset_token = create_password_reset_token(db, user) if user else None
    if user:
        write_audit_log(db, action="auth.password_reset_requested", actor_user_id=user.id)
    db.commit()
    response = {"message": "If the account exists, reset instructions have been issued."}
    if reset_token and get_settings().app_env != "production":
        response["reset_token"] = reset_token
    return response


@router.post("/auth/reset-password")
def reset_password_endpoint(payload: ResetPasswordRequest, db: Session = Depends(get_db)) -> dict[str, str]:
    reset_password(db, payload.token, payload.new_password)
    db.commit()
    return {"message": "Password has been reset."}


@router.get("/auth/me", response_model=UserRead)
def me(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserRead:
    return serialize_user(db, current_user)


@users_router.get("", response_model=list[UserRead])
def list_users(
    current_user: User = Depends(require_permission(Permission.USER_READ)),
    db: Session = Depends(get_db),
) -> list[UserRead]:
    query = select(User)
    if current_user.organization_id:
        query = query.where(User.organization_id == current_user.organization_id)
    users = db.scalars(query.order_by(User.created_at.desc())).all()
    return [serialize_user(db, user) for user in users]


@users_router.get("/permissions")
def list_permissions(_: User = Depends(require_permission(Permission.USER_READ))) -> dict[str, list[str]]:
    return {"permissions": [permission.value for permission in Permission]}


@users_router.get("/roles")
def list_roles(
    current_user: User = Depends(require_permission(Permission.USER_READ)),
    db: Session = Depends(get_db),
) -> list[dict]:
    query = select(Role)
    if current_user.organization_id:
        query = query.where((Role.organization_id == current_user.organization_id) | (Role.is_system.is_(True)))
    roles = db.scalars(query.order_by(Role.name)).all()
    return [{"id": role.id, "name": role.name, "description": role.description} for role in roles]


@users_router.get("/me/settings", response_model=UserSettingsRead)
def get_user_settings(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UserSettingsRead:
    settings = db.scalar(select(UserSettings).where(UserSettings.user_id == current_user.id))
    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return UserSettingsRead(
        email_notifications=settings.email_notifications,
        security_alerts=settings.security_alerts,
    )


@users_router.patch("/me/profile", response_model=UserRead)
def update_profile(
    payload: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserRead:
    current_user.full_name = payload.full_name
    current_user.department_id = payload.department_id
    write_audit_log(db, action="user.profile_updated", actor_user_id=current_user.id)
    db.commit()
    db.refresh(current_user)
    return serialize_user(db, current_user)


@users_router.patch("/me/settings", response_model=UserSettingsRead)
def update_user_settings(
    payload: UserSettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserSettingsRead:
    settings = db.scalar(select(UserSettings).where(UserSettings.user_id == current_user.id))
    if not settings:
        settings = UserSettings(user_id=current_user.id)
        db.add(settings)
    settings.email_notifications = payload.email_notifications
    settings.security_alerts = payload.security_alerts
    write_audit_log(db, action="user.settings_updated", actor_user_id=current_user.id)
    db.commit()
    return UserSettingsRead(**payload.model_dump())


@users_router.patch("/{user_id}/roles", response_model=UserRead)
def assign_user_roles(
    user_id: UUID,
    role_ids: list[UUID],
    current_user: User = Depends(require_permission(Permission.ROLE_ASSIGN)),
    db: Session = Depends(get_db),
) -> UserRead:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if current_user.organization_id and user.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization access denied")
    db.query(UserRole).filter(UserRole.user_id == user.id).delete()
    for role_id in role_ids:
        role = db.get(Role, role_id)
        if not role:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
        db.add(UserRole(user_id=user.id, role_id=role.id))
    write_audit_log(db, action="user.roles_assigned", actor_user_id=current_user.id, target_type="user", target_id=user.id)
    db.commit()
    return serialize_user(db, user)
