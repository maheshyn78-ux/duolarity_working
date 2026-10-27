from datetime import timedelta
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_permission
from app.auth.models import Invitation, Role, User, UserRole
from app.common.audit import write_audit_log
from app.core.config import get_settings
from app.core.permissions import Permission
from app.core.security import generate_opaque_token, hash_password, hash_token, utcnow
from app.db.session import get_db
from app.organizations.models import Department, Organization
from app.organizations.schemas import (
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    InviteUserRequest,
    InviteUserResponse,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)

router = APIRouter(prefix="/organizations", tags=["Organizations"])


def ensure_org_scope(current_user: User, organization_id: UUID) -> None:
    if current_user.organization_id and current_user.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization access denied")


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(require_permission(Permission.ORGANIZATION_CREATE)),
    db: Session = Depends(get_db),
) -> Organization:
    organization = Organization(**payload.model_dump())
    db.add(organization)
    db.flush()
    write_audit_log(
        db,
        action="organization.created",
        actor_user_id=current_user.id,
        organization_id=organization.id,
        target_type="organization",
        target_id=organization.id,
    )
    db.commit()
    db.refresh(organization)
    return organization


@router.get("", response_model=list[OrganizationRead])
def list_organizations(
    current_user: User = Depends(require_permission(Permission.ORGANIZATION_READ)),
    db: Session = Depends(get_db),
) -> list[Organization]:
    query = select(Organization)
    if current_user.organization_id:
        query = query.where(Organization.id == current_user.organization_id)
    return list(db.scalars(query.order_by(Organization.name)).all())


@router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: UUID,
    current_user: User = Depends(require_permission(Permission.ORGANIZATION_READ)),
    db: Session = Depends(get_db),
) -> Organization:
    ensure_org_scope(current_user, organization_id)
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    return organization


@router.patch("/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    current_user: User = Depends(require_permission(Permission.ORGANIZATION_UPDATE)),
    db: Session = Depends(get_db),
) -> Organization:
    ensure_org_scope(current_user, organization_id)
    organization = db.get(Organization, organization_id)
    if not organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(organization, field, value)
    write_audit_log(db, action="organization.updated", actor_user_id=current_user.id, organization_id=organization.id)
    db.commit()
    db.refresh(organization)
    return organization


@router.post("/{organization_id}/departments", response_model=DepartmentRead, status_code=status.HTTP_201_CREATED)
def create_department(
    organization_id: UUID,
    payload: DepartmentCreate,
    current_user: User = Depends(require_permission(Permission.DEPARTMENT_MANAGE)),
    db: Session = Depends(get_db),
) -> Department:
    ensure_org_scope(current_user, organization_id)
    department = Department(organization_id=organization_id, **payload.model_dump())
    db.add(department)
    write_audit_log(db, action="department.created", actor_user_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(department)
    return department


@router.get("/{organization_id}/departments", response_model=list[DepartmentRead])
def list_departments(
    organization_id: UUID,
    current_user: User = Depends(require_permission(Permission.ORGANIZATION_READ)),
    db: Session = Depends(get_db),
) -> list[Department]:
    ensure_org_scope(current_user, organization_id)
    return list(
        db.scalars(select(Department).where(Department.organization_id == organization_id).order_by(Department.name)).all()
    )


@router.patch("/{organization_id}/departments/{department_id}", response_model=DepartmentRead)
def update_department(
    organization_id: UUID,
    department_id: UUID,
    payload: DepartmentUpdate,
    current_user: User = Depends(require_permission(Permission.DEPARTMENT_MANAGE)),
    db: Session = Depends(get_db),
) -> Department:
    ensure_org_scope(current_user, organization_id)
    department = db.get(Department, department_id)
    if not department or department.organization_id != organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Department not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(department, field, value)
    write_audit_log(db, action="department.updated", actor_user_id=current_user.id, organization_id=organization_id)
    db.commit()
    db.refresh(department)
    return department


@router.post("/{organization_id}/invites", response_model=InviteUserResponse, status_code=status.HTTP_201_CREATED)
def invite_user(
    organization_id: UUID,
    payload: InviteUserRequest,
    current_user: User = Depends(require_permission(Permission.USER_INVITE)),
    db: Session = Depends(get_db),
) -> InviteUserResponse:
    ensure_org_scope(current_user, organization_id)
    role = db.get(Role, payload.role_id)
    if not role:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        existing.organization_id = organization_id
        existing.department_id = payload.department_id
        if not db.scalar(select(UserRole).where(UserRole.user_id == existing.id, UserRole.role_id == role.id)):
            db.add(UserRole(user_id=existing.id, role_id=role.id))
        invitation_id = existing.id
        invite_token = None
    else:
        temp_password = generate_opaque_token()
        user = User(
            organization_id=organization_id,
            department_id=payload.department_id,
            email=payload.email.lower(),
            full_name=payload.full_name,
            password_hash=hash_password(temp_password),
            status="invited",
        )
        db.add(user)
        db.flush()
        db.add(UserRole(user_id=user.id, role_id=role.id))
        invite_token = generate_opaque_token()
        invitation = Invitation(
            organization_id=organization_id,
            email=payload.email.lower(),
            role_id=role.id,
            invited_by_user_id=current_user.id,
            token_hash=hash_token(invite_token),
            expires_at=utcnow() + timedelta(days=7),
        )
        db.add(invitation)
        db.flush()
        invitation_id = invitation.id
    write_audit_log(db, action="user.invited", actor_user_id=current_user.id, organization_id=organization_id)
    db.commit()
    return InviteUserResponse(
        invitation_id=invitation_id,
        email=payload.email,
        invite_token=invite_token if get_settings().app_env != "production" else None,
    )
