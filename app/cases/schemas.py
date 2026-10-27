from uuid import UUID

from pydantic import BaseModel, Field


class CaseCreate(BaseModel):
    title: str = Field(min_length=2, max_length=220)
    description: str | None = None
    company_name: str | None = Field(default=None, max_length=180)
    organization_id: UUID | None = None
    assigned_organization_id: UUID | None = None


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    description: str | None = None
    company_name: str | None = Field(default=None, max_length=180)
    status: str | None = None
    assigned_organization_id: UUID | None = None


class CaseRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    company_name: str | None
    case_number: str
    title: str
    description: str | None
    status: str
    created_by_user_id: UUID
    assigned_organization_id: UUID | None

    model_config = {"from_attributes": True}


class CaseAssignUsersRequest(BaseModel):
    user_ids: list[UUID]


class CaseActivityRead(BaseModel):
    id: UUID
    case_id: UUID
    actor_user_id: UUID | None
    action: str
    description: str
    metadata_json: dict

    model_config = {"from_attributes": True}
