from uuid import UUID

from pydantic import BaseModel, Field


class DocumentCreate(BaseModel):
    case_id: UUID | None = None
    title: str = Field(min_length=2, max_length=220)
    category: str = Field(default="uncategorized", max_length=80)
    description: str | None = None


class DocumentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=2, max_length=220)
    category: str | None = Field(default=None, max_length=80)
    description: str | None = None


class DocumentFileRead(BaseModel):
    id: UUID
    document_id: UUID
    version: int
    original_filename: str
    mime_type: str
    size_bytes: int
    file_hash: str
    is_current: bool

    model_config = {"from_attributes": True}


class DocumentRead(BaseModel):
    id: UUID
    organization_id: UUID | None
    case_id: UUID | None
    uploaded_by_user_id: UUID
    title: str
    category: str
    status: str
    description: str | None
    files: list[DocumentFileRead] = []

    model_config = {"from_attributes": True}
