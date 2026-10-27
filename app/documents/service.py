from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import User
from app.documents.models import Document, DocumentFile, DocumentMetadata
from app.documents.storage import LocalStorage


def build_storage_key(organization_id: UUID | None, document_id: UUID, version: int, filename: str) -> str:
    org = str(organization_id) if organization_id else "system"
    safe_name = Path(filename).name.replace("\\", "_").replace("/", "_")
    return f"organizations/{org}/documents/{document_id}/v{version}/{uuid4()}-{safe_name}"


async def create_document_with_file(
    db: Session,
    *,
    current_user: User,
    title: str,
    category: str,
    description: str | None,
    case_id: UUID | None,
    upload: UploadFile,
    storage: LocalStorage,
) -> Document:
    document = Document(
        organization_id=current_user.organization_id,
        case_id=case_id,
        uploaded_by_user_id=current_user.id,
        title=title,
        category=category,
        description=description,
    )
    db.add(document)
    db.flush()
    storage_key = build_storage_key(current_user.organization_id, document.id, 1, upload.filename or "document")
    stored = await storage.save_upload(upload, storage_key)
    db.add(
        DocumentFile(
            document_id=document.id,
            version=1,
            original_filename=upload.filename or "document",
            mime_type=upload.content_type or "application/octet-stream",
            size_bytes=stored.size_bytes,
            file_hash=stored.file_hash,
            storage_key=stored.storage_key,
            is_current=True,
        )
    )
    db.add(
        DocumentMetadata(
            document_id=document.id,
            metadata_json={
                "filename": upload.filename,
                "content_type": upload.content_type,
                "size_bytes": stored.size_bytes,
            },
        )
    )
    return document


async def add_document_version(
    db: Session,
    *,
    document: Document,
    upload: UploadFile,
    storage: LocalStorage,
) -> DocumentFile:
    current_versions = db.scalars(select(DocumentFile).where(DocumentFile.document_id == document.id)).all()
    for version in current_versions:
        version.is_current = False
    next_version = max([version.version for version in current_versions], default=0) + 1
    storage_key = build_storage_key(document.organization_id, document.id, next_version, upload.filename or "document")
    stored = await storage.save_upload(upload, storage_key)
    document_file = DocumentFile(
        document_id=document.id,
        version=next_version,
        original_filename=upload.filename or "document",
        mime_type=upload.content_type or "application/octet-stream",
        size_bytes=stored.size_bytes,
        file_hash=stored.file_hash,
        storage_key=stored.storage_key,
        is_current=True,
    )
    db.add(document_file)
    return document_file
