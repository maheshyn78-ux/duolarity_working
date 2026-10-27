from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.auth.deps import require_permission
from app.auth.models import User
from app.common.audit import write_audit_log
from app.core.permissions import Permission
from app.db.session import get_db
from app.documents.models import Document, DocumentFile
from app.documents.schemas import DocumentRead, DocumentUpdate
from app.documents.service import add_document_version, create_document_with_file
from app.documents.storage import LocalStorage

router = APIRouter(prefix="/documents", tags=["Documents"])


def get_storage() -> LocalStorage:
    return LocalStorage()


def ensure_document_scope(current_user: User, document: Document) -> None:
    if current_user.organization_id and document.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Document access denied")


@router.post("", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: str = Form(...),
    category: str = Form("uncategorized"),
    description: str | None = Form(None),
    case_id: UUID | None = Form(None),
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
) -> Document:
    document = await create_document_with_file(
        db,
        current_user=current_user,
        title=title,
        category=category,
        description=description,
        case_id=case_id,
        upload=file,
        storage=storage,
    )
    write_audit_log(db, action="document.uploaded", actor_user_id=current_user.id, organization_id=document.organization_id)
    db.commit()
    db.refresh(document)
    return db.scalar(select(Document).options(selectinload(Document.files)).where(Document.id == document.id))


@router.get("", response_model=list[DocumentRead])
def search_documents(
    q: str | None = None,
    category: str | None = None,
    case_id: UUID | None = None,
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: Session = Depends(get_db),
) -> list[Document]:
    query = select(Document).options(selectinload(Document.files))
    if current_user.organization_id:
        query = query.where(Document.organization_id == current_user.organization_id)
    if q:
        query = query.where(or_(Document.title.ilike(f"%{q}%"), Document.description.ilike(f"%{q}%")))
    if category:
        query = query.where(Document.category == category)
    if case_id:
        query = query.where(Document.case_id == case_id)
    return list(db.scalars(query.order_by(Document.created_at.desc())).all())


@router.get("/{document_id}", response_model=DocumentRead)
def get_document(
    document_id: UUID,
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: Session = Depends(get_db),
) -> Document:
    document = db.scalar(select(Document).options(selectinload(Document.files)).where(Document.id == document_id))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    ensure_document_scope(current_user, document)
    return document


@router.patch("/{document_id}", response_model=DocumentRead)
def update_document(
    document_id: UUID,
    payload: DocumentUpdate,
    current_user: User = Depends(require_permission(Permission.DOCUMENT_UPDATE)),
    db: Session = Depends(get_db),
) -> Document:
    document = db.scalar(select(Document).options(selectinload(Document.files)).where(Document.id == document_id))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    ensure_document_scope(current_user, document)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(document, field, value)
    write_audit_log(db, action="document.updated", actor_user_id=current_user.id, organization_id=document.organization_id)
    db.commit()
    db.refresh(document)
    return document


@router.post("/{document_id}/versions", response_model=DocumentRead)
async def upload_document_version(
    document_id: UUID,
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission(Permission.DOCUMENT_UPLOAD)),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
) -> Document:
    document = db.scalar(select(Document).options(selectinload(Document.files)).where(Document.id == document_id))
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    ensure_document_scope(current_user, document)
    await add_document_version(db, document=document, upload=file, storage=storage)
    write_audit_log(db, action="document.version_uploaded", actor_user_id=current_user.id, organization_id=document.organization_id)
    db.commit()
    db.refresh(document)
    return db.scalar(select(Document).options(selectinload(Document.files)).where(Document.id == document.id))


@router.get("/{document_id}/download")
def download_document(
    document_id: UUID,
    version: int | None = None,
    current_user: User = Depends(require_permission(Permission.DOCUMENT_READ)),
    db: Session = Depends(get_db),
    storage: LocalStorage = Depends(get_storage),
) -> FileResponse:
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    ensure_document_scope(current_user, document)
    query = select(DocumentFile).where(DocumentFile.document_id == document_id)
    query = query.where(DocumentFile.version == version) if version else query.where(DocumentFile.is_current.is_(True))
    document_file = db.scalar(query)
    if not document_file:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")
    path = storage.resolve(document_file.storage_key)
    return FileResponse(path, filename=document_file.original_filename, media_type=document_file.mime_type)
