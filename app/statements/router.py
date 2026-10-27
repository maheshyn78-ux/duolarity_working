import csv
import io
import re
import uuid
from datetime import date
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import chat as ai_chat
from app.ai import llm
from app.auth.deps import get_current_user
from app.auth.models import User
from app.core.config import get_settings
from app.db.session import get_db
from app.documents.storage import LocalStorage
from app.statements.extract import SUPPORTED
from app.statements.models import Statement, Transaction, Workspace
from app.statements.pipeline import STEPS, run_statement_job
from app.statements.reports import REPORT_TYPES, build_report

router = APIRouter(tags=["Statements & AI"])


# ------------------------------------------------------------------ helpers
def _own(db: Session, user: User, sid: uuid.UUID) -> Statement:
    st = db.get(Statement, sid)
    if not st or st.owner_user_id != user.id:
        raise HTTPException(404, "Statement not found")
    return st


def _txns(db: Session, st: Statement) -> list[Transaction]:
    return list(db.scalars(select(Transaction).where(Transaction.statement_id == st.id).order_by(Transaction.seq)))


def _f(x):
    return float(x) if x is not None else None


def serialize_statement(st: Statement, full: bool = False) -> dict:
    cur_idx = next((i for i, (name, _) in enumerate(STEPS) if st.stage.startswith(name.split(" (")[0])), 0)
    steps = []
    for i, (name, desc) in enumerate(STEPS):
        state = "done" if st.status == "completed" or i < cur_idx else ("active" if i == cur_idx and st.status in ("processing", "queued") else "pending")
        if st.status == "failed" and i == cur_idx:
            state = "failed"
        steps.append({"name": name, "description": desc, "state": state})
    d = {
        "id": str(st.id), "workspace_id": str(st.workspace_id) if st.workspace_id else None, "filename": st.filename,
        "size_bytes": st.size_bytes, "status": st.status, "stage": st.stage, "progress": st.progress, "steps": steps,
        "pages_total": st.pages_total, "pages_done": st.pages_done, "method": st.method, "error": st.error,
        "bank_name": st.bank_name, "account_holder": st.account_holder, "account_number": st.account_number,
        "currency": st.currency, "period_start": st.period_start.isoformat() if st.period_start else None,
        "period_end": st.period_end.isoformat() if st.period_end else None,
        "opening_balance": _f(st.opening_balance), "closing_balance": _f(st.closing_balance),
        "txn_count": st.txn_count, "total_debit": _f(st.total_debit), "total_credit": _f(st.total_credit),
        "flagged_count": st.flagged_count, "created_at": st.created_at.isoformat() if st.created_at else None,
    }
    if full:
        d["summary"] = st.summary_json or {}
        d["ai_summary"] = st.ai_summary
    return d


def serialize_txn(t: Transaction) -> dict:
    return {
        "id": str(t.id), "seq": t.seq, "date": t.txn_date.isoformat() if t.txn_date else None, "description": t.description,
        "reference": t.reference, "debit": _f(t.debit), "credit": _f(t.credit), "balance": _f(t.balance),
        "category": t.category, "ledger_head": t.ledger_head, "category_source": t.category_source,
        "flagged": t.is_flagged, "flag_reason": t.flag_reason, "page": t.page,
    }


# ------------------------------------------------------------------ AI status
@router.get("/ai/status")
def ai_status(force: bool = False, _: User = Depends(get_current_user)) -> dict:
    return llm.status(force=force)


# ------------------------------------------------------------------ workspaces
class WorkspaceIn(BaseModel):
    client_name: str = Field(min_length=1, max_length=180)
    company: str = ""
    industry: str = ""


def _ws(w: Workspace) -> dict:
    return {"id": str(w.id), "client_name": w.client_name, "company": w.company, "industry": w.industry}


@router.get("/workspaces")
def list_workspaces(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    rows = db.scalars(select(Workspace).where(Workspace.owner_user_id == user.id).order_by(Workspace.created_at))
    return [_ws(w) for w in rows]


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    w = Workspace(owner_user_id=user.id, client_name=body.client_name.strip(), company=body.company.strip(), industry=body.industry.strip())
    db.add(w)
    db.commit()
    return _ws(w)


@router.delete("/workspaces/{wid}", status_code=204)
def delete_workspace(wid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    w = db.get(Workspace, wid)
    if not w or w.owner_user_id != user.id:
        raise HTTPException(404, "Workspace not found")
    for st in db.scalars(select(Statement).where(Statement.workspace_id == wid)):
        st.workspace_id = None
    db.delete(w)
    db.commit()


# ------------------------------------------------------------------ statements
@router.post("/statements", status_code=202)
async def upload_statement(
    background: BackgroundTasks,
    file: UploadFile = File(...),
    workspace_id: uuid.UUID | None = Form(None),
    password: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    s = get_settings()
    filename = Path(file.filename or "statement").name
    if Path(filename).suffix.lower() not in SUPPORTED:
        raise HTTPException(415, f"Unsupported file type. Allowed: {', '.join(sorted(SUPPORTED))}")
    if workspace_id:
        w = db.get(Workspace, workspace_id)
        if not w or w.owner_user_id != user.id:
            raise HTTPException(404, "Workspace not found")
    sid = uuid.uuid4()
    key = f"statements/{user.id}/{sid}{Path(filename).suffix.lower()}"
    stored = await LocalStorage().save_upload(file, key)
    if stored.size_bytes == 0:
        LocalStorage().resolve(key).unlink(missing_ok=True)
        raise HTTPException(400, "The uploaded file is empty")
    if stored.size_bytes > s.max_upload_mb * 1024 * 1024:
        LocalStorage().resolve(key).unlink(missing_ok=True)
        raise HTTPException(413, f"File exceeds {s.max_upload_mb} MB limit")
    st = Statement(
        id=sid, owner_user_id=user.id, workspace_id=workspace_id, filename=filename, mime_type=file.content_type or "",
        size_bytes=stored.size_bytes, file_hash=stored.file_hash, storage_key=key, status="queued", stage="Queued", progress=1,
    )
    db.add(st)
    db.commit()
    background.add_task(run_statement_job, sid, password)
    return serialize_statement(st)


@router.get("/statements")
def list_statements(workspace_id: uuid.UUID | None = None, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> list[dict]:
    q = select(Statement).where(Statement.owner_user_id == user.id).order_by(Statement.created_at.desc())
    if workspace_id:
        q = q.where(Statement.workspace_id == workspace_id)
    return [serialize_statement(x) for x in db.scalars(q)]


@router.get("/statements/{sid}")
def get_statement(sid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    return serialize_statement(_own(db, user, sid), full=True)


@router.post("/statements/{sid}/reprocess", status_code=202)
def reprocess(sid: uuid.UUID, background: BackgroundTasks, password: str | None = Form(None), db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    st = _own(db, user, sid)
    st.status, st.stage, st.progress, st.error = "queued", "Queued", 1, None
    db.commit()
    background.add_task(run_statement_job, sid, password)
    return serialize_statement(st)


@router.delete("/statements/{sid}", status_code=204)
def delete_statement(sid: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> None:
    st = _own(db, user, sid)
    for t in _txns(db, st):
        db.delete(t)
    try:
        LocalStorage().resolve(st.storage_key).unlink(missing_ok=True)
    except Exception:  # noqa: BLE001
        pass
    db.delete(st)
    db.commit()


@router.get("/statements/{sid}/transactions")
def transactions(
    sid: uuid.UUID,
    q: str | None = None,
    category: str | None = None,
    flagged: bool | None = None,
    direction: str | None = Query(None, pattern="^(debit|credit)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=1000),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    st = _own(db, user, sid)
    base = select(Transaction).where(Transaction.statement_id == st.id)
    if q:
        base = base.where(Transaction.description.ilike(f"%{q}%"))
    if category:
        base = base.where(Transaction.category == category)
    if flagged is not None:
        base = base.where(Transaction.is_flagged.is_(flagged))
    if direction == "debit":
        base = base.where(Transaction.debit > 0)
    elif direction == "credit":
        base = base.where(Transaction.credit > 0)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Transaction.seq).offset((page - 1) * page_size).limit(page_size))
    return {"total": total, "page": page, "page_size": page_size, "items": [serialize_txn(t) for t in rows]}


class TxnPatch(BaseModel):
    category: str


@router.patch("/statements/{sid}/transactions/{tid}")
def recategorize(sid: uuid.UUID, tid: uuid.UUID, body: TxnPatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    from app.statements.categorize import CATEGORIES, head_for

    st = _own(db, user, sid)
    t = db.get(Transaction, tid)
    if not t or t.statement_id != st.id:
        raise HTTPException(404, "Transaction not found")
    if body.category not in CATEGORIES:
        raise HTTPException(422, "Unknown category")
    t.category, t.ledger_head, t.category_source = body.category, head_for(body.category), "manual"
    db.commit()
    return serialize_txn(t)


@router.get("/reports/types")
def report_types(_: User = Depends(get_current_user)) -> list[str]:
    return REPORT_TYPES


@router.get("/statements/{sid}/report")
def report(sid: uuid.UUID, type: str = "Trial Balance", db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    st = _own(db, user, sid)
    if st.status != "completed":
        raise HTTPException(409, "Statement is still processing")
    if type not in REPORT_TYPES:
        raise HTTPException(422, f"type must be one of {REPORT_TYPES}")
    return build_report(type, st, _txns(db, st))


@router.get("/statements/{sid}/export")
def export(sid: uuid.UUID, format: str = Query("csv", pattern="^(csv|xlsx)$"), db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    st = _own(db, user, sid)
    rows = _txns(db, st)
    header = ["Date", "Description", "Reference", "Debit", "Credit", "Balance", "Category", "Ledger Head", "Flag"]
    data = [[t.txn_date.isoformat() if t.txn_date else "", t.description, t.reference or "", _f(t.debit), _f(t.credit), _f(t.balance), t.category, t.ledger_head, t.flag_reason or ""] for t in rows]
    base = re.sub(r"[^\w.-]+", "_", Path(st.filename).stem)
    if format == "xlsx":
        import openpyxl

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Transactions"
        ws.append(header)
        for r in data:
            ws.append(r)
        ws2 = wb.create_sheet("Reports")
        for kind in ("Trial Balance", "P&L Statement", "Cash Flow", "Category Breakdown"):
            rep = build_report(kind, st, rows)
            ws2.append([rep["title"]])
            ws2.append(rep["columns"])
            for r in rep["rows"]:
                ws2.append(r)
            if rep["total"]:
                ws2.append(rep["total"])
            ws2.append([])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                 headers={"Content-Disposition": f'attachment; filename="{base}.xlsx"'})
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(header)
    w.writerows(data)
    return StreamingResponse(iter([out.getvalue()]), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{base}.csv"'})


# ------------------------------------------------------------------ AI chat
class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    statement_id: uuid.UUID | None = None
    workspace_id: uuid.UUID | None = None
    history: list[dict] = []


@router.post("/ai/chat")
def chat(body: ChatIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    if body.statement_id:
        st = _own(db, user, body.statement_id)
    else:
        q = select(Statement).where(Statement.owner_user_id == user.id, Statement.status == "completed").order_by(Statement.created_at.desc())
        if body.workspace_id:
            q = q.where(Statement.workspace_id == body.workspace_id)
        st = db.scalars(q).first()
        if not st:
            if llm.is_available():
                try:
                    return {"answer": llm.chat([{"role": "system", "content": "You are Duolarity AI, an accounting assistant. No statement is uploaded yet; answer general finance questions briefly and invite the user to upload a bank statement."}, {"role": "user", "content": body.message}], temperature=0.3, max_tokens=400), "engine": "ollama", "matches": 0}
                except llm.LLMUnavailable:
                    pass
            return {"answer": "Upload a bank statement first (PDF, CSV or Excel) and I can analyse it.", "engine": "rules", "matches": 0}
    if st.status != "completed":
        raise HTTPException(409, "Statement is still processing")
    return {**ai_chat.answer(db, st, body.message, body.history), "statement_id": str(st.id)}
