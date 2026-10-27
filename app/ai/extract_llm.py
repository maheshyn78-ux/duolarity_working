"""LLM extraction for statements the rule parser can't read (odd layouts, OCR noise, mixed formats).

Long documents are processed map-reduce style: split into line-aligned chunks that fit the model's context,
extract per chunk, and carry the previous running balance forward so debit/credit can be inferred.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from decimal import Decimal

from app.ai import llm
from app.core.config import get_settings
from app.statements.parse import ZERO, RawTxn, detect_dayfirst, parse_date, to_decimal

log = logging.getLogger(__name__)

SYSTEM = (
    "You are a precise bank-statement parser. Extract EVERY transaction row from the text. "
    "Ignore headers, footers, page numbers, summaries and marketing text. Never invent rows. "
    'Reply with JSON only: {"transactions":[{"date":"YYYY-MM-DD","description":"...","reference":"","debit":0,"credit":0,"balance":null}]}. '
    "Use plain numbers (no commas/currency). A withdrawal/debit goes in 'debit', a deposit/credit in 'credit' (the other is 0). "
    "If a running balance is shown, put it in 'balance'. Dates must be ISO; assume {dayfirst} for ambiguous numeric dates."
)


def chunk_pages(pages: list[str], max_chars: int) -> list[tuple[str, int]]:
    """Return (text, first_page_no) chunks split on line boundaries."""
    chunks: list[tuple[str, int]] = []
    buf: list[str] = []
    size, first = 0, 1
    for pno, page in enumerate(pages, start=1):
        for line in page.splitlines():
            if not line.strip():
                continue
            if size + len(line) > max_chars and buf:
                chunks.append(("\n".join(buf), first))
                buf, size, first = [], 0, pno
            buf.append(line)
            size += len(line) + 1
    if buf:
        chunks.append(("\n".join(buf), first))
    return chunks


def extract_with_llm(pages: list[str], progress: Callable[[int, int], None] | None = None) -> list[RawTxn]:
    s = get_settings()
    dayfirst = detect_dayfirst(pages)
    chunks = chunk_pages(pages, s.ai_chunk_chars)
    out: list[RawTxn] = []
    last_balance: Decimal | None = None
    for i, (text, first_page) in enumerate(chunks, start=1):
        hint = f"\nPrevious running balance before this text: {last_balance}." if last_balance is not None else ""
        msgs = [
            {"role": "system", "content": SYSTEM.replace("{dayfirst}", "day-first (DD/MM)" if dayfirst else "month-first (MM/DD)")},
            {"role": "user", "content": f"Statement text:{hint}\n\n{text}"},
        ]
        try:
            data = llm.chat_json(msgs)
        except llm.LLMUnavailable:
            raise
        except Exception as e:
            log.warning("LLM chunk %s/%s failed: %s", i, len(chunks), e)
            continue
        rows = data.get("transactions", data) if isinstance(data, dict) else data
        for r in rows if isinstance(rows, list) else []:
            if not isinstance(r, dict):
                continue
            d = parse_date(str(r.get("date", "")), dayfirst)
            debit = abs(to_decimal(str(r.get("debit", 0))) or ZERO)
            credit = abs(to_decimal(str(r.get("credit", 0))) or ZERO)
            if not d or (not debit and not credit):
                continue
            bal = to_decimal(str(r["balance"])) if r.get("balance") not in (None, "", "null") else None
            t = RawTxn(date=d, description=str(r.get("description", "")).strip(), debit=debit, credit=credit, balance=bal,
                       reference=(str(r.get("reference") or "")[:120] or None), page=first_page)
            t.amount = debit or credit
            t.direction = "debit" if debit else "credit"
            out.append(t)
            if bal is not None:
                last_balance = bal
        if progress:
            progress(i, len(chunks))
    return out
