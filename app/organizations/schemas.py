from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=180)
    type: str = Field(default="enterprise", max_length=60)
    description: str | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=180)
    type: str | None = Field(default=None, max_length=60)
    status: str | None = Field(default=None, max_length=30)
    description: str | None = None


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    type: str
    status: str
    description: str | None

    model_config = {"from_attributes": True}


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = None


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = None
    is_active: bool | None = None


class DepartmentRead(BaseModel):
    id: UUID
    organization_id: UUID
    name: str
    description: str | None
    is_active: bool

    model_config = {"from_attributes": True}


class InviteUserRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=180)
    role_id: UUID
    department_id: UUID | None = None


class InviteUserResponse(BaseModel):
    invitation_id: UUID
    email: EmailStr
    invite_token: str | None = None
