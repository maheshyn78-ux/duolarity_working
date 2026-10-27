from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.deps import require_permission
from app.auth.models import User
from app.cases.models import Case, CaseActivity, CaseAssignment, CaseStatus
from app.cases.schemas import CaseActivityRead, CaseAssignUsersRequest, CaseCreate, CaseRead, CaseUpdate
from app.cases.service import add_case_activity, create_case
from app.common.audit import write_audit_log
from app.core.permissions import Permission
from app.db.session import get_db

router = APIRouter(prefix="/cases", tags=["Cases"])


def ensure_case_scope(current_user: User, case: Case) -> None:
    if current_user.organization_id and case.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Case access denied")


@router.post("", response_model=CaseRead, status_code=status.HTTP_201_CREATED)
def create_case_endpoint(
    payload: CaseCreate,
    current_user: User = Depends(require_permission(Permission.CASE_CREATE)),
    db: Session = Depends(get_db),
) -> Case:
    if current_user.organization_id and payload.organization_id not in (None, current_user.organization_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Organization access denied")
    case = create_case(db, payload, current_user)
    write_audit_log(db, action="case.created", actor_user_id=current_user.id, organization_id=case.organization_id)
    db.commit()
    db.refresh(case)
    return case


@router.get("", response_model=list[CaseRead])
def list_cases(
    current_user: User = Depends(require_permission(Permission.CASE_READ)),
    db: Session = Depends(get_db),
) -> list[Case]:
    query = select(Case)
    if current_user.organization_id:
        query = query.where(Case.organization_id == current_user.organization_id)
    return list(db.scalars(query.order_by(Case.created_at.desc())).all())


@router.get("/{case_id}", response_model=CaseRead)
def get_case(
    case_id: UUID,
    current_user: User = Depends(require_permission(Permission.CASE_READ)),
    db: Session = Depends(get_db),
) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    ensure_case_scope(current_user, case)
    return case


@router.patch("/{case_id}", response_model=CaseRead)
def update_case(
    case_id: UUID,
    payload: CaseUpdate,
    current_user: User = Depends(require_permission(Permission.CASE_UPDATE)),
    db: Session = Depends(get_db),
) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    ensure_case_scope(current_user, case)
    values = payload.model_dump(exclude_unset=True)
    if "status" in values and values["status"] not in [status.value for status in CaseStatus]:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid case status")
    for field, value in values.items():
        setattr(case, field, value)
    add_case_activity(
        db,
        case_id=case.id,
        actor_user_id=current_user.id,
        action="case.updated",
        description="Case updated",
        metadata=values,
    )
    write_audit_log(db, action="case.updated", actor_user_id=current_user.id, organization_id=case.organization_id)
    db.commit()
    db.refresh(case)
    return case


@router.post("/{case_id}/assign-users", response_model=CaseRead)
def assign_case_users(
    case_id: UUID,
    payload: CaseAssignUsersRequest,
    current_user: User = Depends(require_permission(Permission.CASE_ASSIGN)),
    db: Session = Depends(get_db),
) -> Case:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    ensure_case_scope(current_user, case)
    db.query(CaseAssignment).filter(CaseAssignment.case_id == case.id).delete()
    for user_id in payload.user_ids:
        user = db.get(User, user_id)
        if not user or (current_user.organization_id and user.organization_id != current_user.organization_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned user not found")
        db.add(CaseAssignment(case_id=case.id, user_id=user.id, assigned_by_user_id=current_user.id))
    add_case_activity(
        db,
        case_id=case.id,
        actor_user_id=current_user.id,
        action="case.users_assigned",
        description="Case users assigned",
        metadata={"user_ids": [str(user_id) for user_id in payload.user_ids]},
    )
    db.commit()
    db.refresh(case)
    return case


@router.get("/{case_id}/timeline", response_model=list[CaseActivityRead])
def get_case_timeline(
    case_id: UUID,
    current_user: User = Depends(require_permission(Permission.CASE_READ)),
    db: Session = Depends(get_db),
) -> list[CaseActivity]:
    case = db.get(Case, case_id)
    if not case:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
    ensure_case_scope(current_user, case)
    return list(
        db.scalars(select(CaseActivity).where(CaseActivity.case_id == case.id).order_by(CaseActivity.created_at)).all()
    )
