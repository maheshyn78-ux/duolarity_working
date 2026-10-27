from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=2, max_length=180)


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=12)


class RoleRead(BaseModel):
    id: UUID
    name: str
    permissions: list[str]

    model_config = {"from_attributes": True}


class UserRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    department_id: UUID | None
    email: EmailStr
    full_name: str
    status: str
    roles: list[str]
    permissions: list[str]


class UserProfileUpdate(BaseModel):
    full_name: str = Field(min_length=2, max_length=180)
    department_id: UUID | None = None


class UserSettingsRead(BaseModel):
    email_notifications: bool = True
    security_alerts: bool = True


class UserSettingsUpdate(BaseModel):
    email_notifications: bool = True
    security_alerts: bool = True
