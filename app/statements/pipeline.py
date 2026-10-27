"""Background job: file -> text -> transactions -> categories -> flags -> summary."""
from __future__ import annotations

import logging
from decimal import Decimal
from pathlib import Path

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.ai import llm
from app.ai.categorize_llm import classify, key_for
from app.ai.extract_llm import extract_with_llm
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.documents.storage import LocalStorage
from app.statements import parse as P
from app.statements.categorize import categorize, head_for
from app.statements.extract import ExtractionError, extract_file
from app.statements.insights import build_summary, flag_transactions
from app.statements.models import Statement, Transaction

log = logging.getLogger(__name__)
ZERO = Decimal("0")

STEPS = [
    ("Ingesting document", "Reading file and detecting format"),
    ("Extracting transactions", "Text/OCR extraction and row parsing"),
    ("Categorizing entries", "Mapping transactions to ledger heads"),
    ("Cross-checking", "Balance reconciliation and anomaly checks"),
    ("Generating report", "Summary and AI commentary"),
]


def _set(db: Session, st: Statement, *, stage: str | None = None, progress: int | None = None, **kw) -> None:
    if stage is not None:
        st.stage = stage
    if progress is not None:
        st.progress = max(st.progress or 0, min(progress, 100))
    for k, v in kw.items():
        setattr(st, k, v)
    db.commit()


def run_statement_job(statement_id, password: str | None = None) -> None:
    with SessionLocal() as db:
        st = db.get(Statement, statement_id)
        if not st:
            return
        try:
            _run(db, st, password)
        except ExtractionError as e:
            db.rollback()
            _set(db, db.get(Statement, statement_id), status="failed", stage="Failed", error=str(e))
        except Exception as e:  # noqa: BLE001
            log.exception("statement %s failed", statement_id)
            db.rollback()
            _set(db, db.get(Statement, statement_id), status="failed", stage="Failed", error=f"Unexpected error: {e}")


def _run(db: Session, st: Statement, password: str | None) -> None:
    s = get_settings()
    _set(db, st, status="processing", stage=STEPS[0][0], progress=3, error=None)
    path: Path = LocalStorage().resolve(st.storage_key)
    db.execute(delete(Transaction).where(Transaction.statement_id == st.id))
    db.commit()

    # ---- 1/2: extract text
    def on_page(done: int, total: int) -> None:
        if done == 1 or done % 5 == 0 or done == total:
            _set(db, st, stage=STEPS[1][0], progress=5 + int(35 * done / max(1, total)), pages_done=done, pages_total=total)

    doc = extract_file(path, st.filename, password, on_page)
    _set(db, st, stage=STEPS[1][0], progress=42, pages_total=max(st.pages_total, len(doc.pages)), pages_done=len(doc.pages))

    # ---- parse (rules first)
    dayfirst = P.detect_dayfirst(doc.pages)
    if doc.kind == "table":
        res = P.parse_table_rows(doc.rows, dayfirst)
        method = "table"
        if len(res.txns) < 1:
            res = P.parse_text_pages(doc.pages, dayfirst)
            method = "rules"
    else:
        res = P.parse_text_pages(doc.pages, dayfirst)
        method = "rules"
    # coverage check: how many dated lines did we turn into transactions?
    weak = len(res.txns) == 0 or (res.dated_lines > 5 and len(res.txns) < 0.6 * res.dated_lines)
    if (weak or s.ai_force_llm_extraction) and llm.is_available():
        _set(db, st, stage="Extracting transactions (AI)", progress=45)

        def on_chunk(i: int, n: int) -> None:
            _set(db, st, stage=f"Extracting transactions (AI {i}/{n})", progress=45 + int(25 * i / max(1, n)))

        llm_txns = extract_with_llm(doc.pages, on_chunk)
        if len(llm_txns) > len(res.txns):
            res.txns = llm_txns
            res.opening_balance = res.opening_balance
            if res.closing_balance is None:
                for t in reversed(llm_txns):
                    if t.balance is not None:
                        res.closing_balance = t.balance
                        break
            if res.opening_balance is None and llm_txns and llm_txns[0].balance is not None:
                f0 = llm_txns[0]
                res.opening_balance = f0.balance - f0.credit + f0.debit
            method = "llm" if not res.dated_lines else "hybrid"
    if not res.txns:
        hint = "" if llm.is_available() else " Start Ollama (see README) to let the AI read unusual layouts."
        raise ExtractionError("No transactions could be detected in this file." + hint)

    # ---- metadata
    meta = P.extract_metadata(doc.pages, res.txns)
    dates = [t.date for t in res.txns if t.date]
    st.bank_name, st.account_holder, st.account_number = meta.get("bank_name"), meta.get("account_holder"), meta.get("account_number")
    st.currency = meta.get("currency", st.currency or "INR")
    st.period_start, st.period_end = (min(dates), max(dates)) if dates else (None, None)
    st.opening_balance, st.closing_balance, st.method = res.opening_balance, res.closing_balance, method
    _set(db, st, stage=STEPS[2][0], progress=72)

    # ---- 3: persist + categorize
    rows: list[Transaction] = []
    for i, t in enumerate(res.txns):
        cat = categorize(t.description, bool(t.credit))
        category, head = cat if cat else ("Uncategorized", "Uncategorized")
        rows.append(Transaction(
            statement_id=st.id, seq=i, txn_date=t.date, description=t.description[:2000], reference=t.reference,
            debit=t.debit, credit=t.credit, balance=t.balance, category=category, ledger_head=head, page=t.page,
        ))
    ai_note = None
    unc = [r for r in rows if r.category == "Uncategorized"]
    if unc and s.ai_categorize_with_llm and llm.is_available():
        _set(db, st, stage="Categorizing entries (AI)", progress=75)
        try:
            mapping = classify([(r.description, bool(r.credit)) for r in unc])
            for r in unc:
                cat = mapping.get(key_for(r.description, bool(r.credit)))
                if cat:
                    r.category, r.ledger_head, r.category_source = cat, head_for(cat), "ai"
        except llm.LLMUnavailable as e:
            ai_note = str(e)
    else:
        # default heads for leftovers so reports still make sense
        for r in unc:
            if r.credit:
                r.ledger_head = "Fund Transfers"
    db.add_all(rows)
    db.commit()

    # ---- 4: checks
    _set(db, st, stage=STEPS[3][0], progress=88)
    st.txn_count = len(rows)
    st.total_debit = sum((r.debit for r in rows), ZERO)
    st.total_credit = sum((r.credit for r in rows), ZERO)
    st.flagged_count = flag_transactions(rows, st)
    summary = build_summary(rows, st)
    summary["extraction"] = {"method": method, "ocr_pages": doc.ocr_pages, "pages": len(doc.pages), "ai_note": ai_note}
    st.summary_json = summary
    db.commit()

    # ---- 5: AI commentary
    _set(db, st, stage=STEPS[4][0], progress=94)
    st.ai_summary = narrative(st, summary)
    _set(db, st, status="completed", stage="Complete", progress=100)


def narrative(st: Statement, summary: dict) -> str:
    """Short plain-language summary. Uses the LLM when available, else a deterministic template."""
    cur = st.currency
    top = ", ".join(f"{c['category']} ({c['debit']:,.0f})" for c in summary["categories"] if c["debit"])[:300]
    base = (
        f"Processed {summary['txn_count']} transactions"
        + (f" from {st.period_start} to {st.period_end}" if st.period_start else "")
        + f". Total credits {summary['total_credit']:,.2f} {cur}, total debits {summary['total_debit']:,.2f} {cur}. "
        f"{summary['flagged']} item(s) flagged for review; reconciliation: {summary['balance_check']['status']}."
    )
    if not llm.is_available():
        return base
    try:
        facts = {k: summary[k] for k in ("txn_count", "total_debit", "total_credit", "net_movement", "balance_check", "flagged", "uncategorized")}
        facts["top_spend_categories"] = [c for c in summary["categories"] if c["debit"]][:6]
        facts["monthly"] = summary["monthly"][:24]
        facts["period"] = f"{st.period_start} to {st.period_end}"
        facts["currency"] = cur
        out = llm.chat(
            [
                {"role": "system", "content": "You are a finance assistant. Write a 3-5 sentence plain-English summary of this bank statement for an accountant. "
                 "Use ONLY the provided figures; do not invent numbers. Mention notable risks."},
                {"role": "user", "content": str(facts)},
            ],
            temperature=0.2, max_tokens=300,
        )
        return out.strip() or base
    except Exception:  # noqa: BLE001
        return base
