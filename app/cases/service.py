from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.cases.models import Case, CaseActivity, CaseAssignment
from app.cases.schemas import CaseCreate


def next_case_number(db: Session) -> str:
    count = db.scalar(select(func.count(Case.id))) or 0
    return f"CASE-{count + 1:06d}"


def add_case_activity(
    db: Session,
    *,
    case_id: UUID,
    action: str,
    description: str,
    actor_user_id: UUID | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        CaseActivity(
            case_id=case_id,
            actor_user_id=actor_user_id,
            action=action,
            description=description,
            metadata_json=metadata or {},
        )
    )


def create_case(db: Session, payload: CaseCreate, current_user: User) -> Case:
    organization_id = payload.organization_id or current_user.organization_id
    case = Case(
        organization_id=organization_id,
        assigned_organization_id=payload.assigned_organization_id,
        company_name=payload.company_name,
        case_number=next_case_number(db),
        title=payload.title,
        description=payload.description,
        created_by_user_id=current_user.id,
    )
    db.add(case)
    db.flush()
    add_case_activity(
        db,
        case_id=case.id,
        actor_user_id=current_user.id,
        action="case.created",
        description="Case created",
    )
    return case
