"""Chat over a processed statement: retrieval (keywords/dates/categories) + local LLM, with a rule-based fallback."""
from __future__ import annotations

import re
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import llm
from app.statements.models import Statement, Transaction
from app.statements.reports import money

STOP = set("the a an of in on for to and or is are was were what how much many did do i my me total show list give all any from with by at this that it its be".split())
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _tokens(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9&]+", q.lower()) if w not in STOP and len(w) > 2]


def retrieve(txns: list[Transaction], question: str, limit: int = 40) -> list[Transaction]:
    toks = _tokens(question)
    q = question.lower()
    month = next((n for k, n in MONTHS.items() if re.search(rf"\b{k}[a-z]*\b", q)), None)
    pool = [t for t in txns if (month is None or (t.txn_date and t.txn_date.month == month))]
    scored = []
    for t in pool:
        hay = f"{t.description} {t.category} {t.ledger_head}".lower()
        score = sum(2 for w in toks if w in hay)
        if score:
            scored.append((score, t))
    scored.sort(key=lambda x: (-x[0], x[1].txn_date or 0))
    hits = [t for _, t in scored[:limit]]
    if not hits and month:
        hits = pool[:limit]
    return hits


def _fmt(t: Transaction, cur: str) -> str:
    amt = f"-{money(t.debit, cur)}" if t.debit else f"+{money(t.credit, cur)}"
    return f"{t.txn_date} | {t.description[:80]} | {amt} | {t.category}"


def answer(db: Session, st: Statement, question: str, history: list[dict] | None = None) -> dict:
    txns = list(db.scalars(select(Transaction).where(Transaction.statement_id == st.id).order_by(Transaction.seq)))
    cur = st.currency
    hits = retrieve(txns, question)
    hit_debit = sum((t.debit for t in hits), Decimal(0))
    hit_credit = sum((t.credit for t in hits), Decimal(0))
    s = st.summary_json or {}
    context = {
        "file": st.filename, "bank": st.bank_name, "period": f"{st.period_start} to {st.period_end}", "currency": cur,
        "opening_balance": float(st.opening_balance) if st.opening_balance is not None else None,
        "closing_balance": float(st.closing_balance) if st.closing_balance is not None else None,
        "txn_count": s.get("txn_count"), "total_debit": s.get("total_debit"), "total_credit": s.get("total_credit"),
        "balance_check": s.get("balance_check", {}).get("status"), "flagged": s.get("flagged"),
        "monthly": s.get("monthly", [])[:24], "categories": s.get("categories", [])[:15],
        "top_debits": s.get("top_debits"), "top_credits": s.get("top_credits"),
    }
    if llm.is_available():
        rel = "\n".join(_fmt(t, cur) for t in hits) or "(no keyword-matching transactions)"
        msgs = [
            {"role": "system", "content": "You are Duolarity AI, a careful accounting assistant. Answer ONLY from the statement data given. "
             "If the data doesn't contain the answer, say so. Quote amounts exactly; do not invent transactions. Be concise."},
        ]
        for h in (history or [])[-6:]:
            if h.get("role") in ("user", "assistant") and h.get("content"):
                msgs.append({"role": h["role"], "content": str(h["content"])[:1500]})
        msgs.append({"role": "user", "content": f"STATEMENT SUMMARY: {context}\n\nMATCHING TRANSACTIONS (sum debit={hit_debit}, sum credit={hit_credit}, n={len(hits)}):\n{rel}\n\nQUESTION: {question}"})
        try:
            return {"answer": llm.chat(msgs, temperature=0.1, max_tokens=700).strip(), "engine": "ollama", "matches": len(hits)}
        except llm.LLMUnavailable:
            pass
    return {"answer": _rule_answer(st, txns, hits, question), "engine": "rules", "matches": len(hits)}


def _rule_answer(st: Statement, txns: list[Transaction], hits: list[Transaction], q: str) -> str:
    cur, ql = st.currency, q.lower()
    s = st.summary_json or {}
    m = lambda x: money(x, cur)  # noqa: E731
    if re.search(r"balance", ql) and st.closing_balance is not None:
        return f"Closing balance is {m(st.closing_balance)}" + (f" (opening {m(st.opening_balance)})." if st.opening_balance is not None else ".")
    if re.search(r"how many|count|number of", ql) and not hits:
        return f"There are {len(txns)} transactions in this statement."
    if re.search(r"flag|suspicious|anomal|duplicate|review", ql):
        fl = [t for t in txns if t.is_flagged][:8]
        return "Flagged items:\n" + "\n".join(f"- {_fmt(t, cur)} [{t.flag_reason}]" for t in fl) if fl else "No transactions were flagged."
    if re.search(r"largest|biggest|highest|top", ql):
        if re.search(r"income|credit|receiv|deposit", ql):
            return "Largest credits:\n" + "\n".join(f"- {r['date']} {r['description'][:60]}: {m(r['credit'])}" for r in s.get("top_credits", []))
        return "Largest debits:\n" + "\n".join(f"- {r['date']} {r['description'][:60]}: {m(r['debit'])}" for r in s.get("top_debits", []))
    if re.search(r"categor|breakdown|where.*(spend|money)", ql):
        return "Top categories:\n" + "\n".join(f"- {c['category']}: debits {m(c['debit'])}, credits {m(c['credit'])}" for c in s.get("categories", [])[:8])
    if hits and _tokens(q):
        d, c = sum((t.debit for t in hits), Decimal(0)), sum((t.credit for t in hits), Decimal(0))
        return f"Found {len(hits)} matching transaction(s): total debits {m(d)}, total credits {m(c)}.\n" + "\n".join(f"- {_fmt(t, cur)}" for t in hits[:6])
    if re.search(r"spen|expens|debit|paid", ql):
        return f"Total debits: {m(s.get('total_debit', 0))} across the statement."
    if re.search(r"income|credit|receiv|deposit", ql):
        return f"Total credits: {m(s.get('total_credit', 0))}."
    return ("The local AI model isn't running, so I can only answer simple questions (balance, totals, largest transactions, categories, "
            "keyword searches). Start Ollama for full conversational answers - see the README.")
