"""Flags + aggregate summary computed from stored transactions."""
from __future__ import annotations

import statistics
from collections import defaultdict
from decimal import Decimal

from app.statements.categorize import NATURE_BY_HEAD
from app.statements.models import Statement, Transaction

ZERO = Decimal("0")
TOL = Decimal("0.05")


def f(x) -> float:
    return float(x or 0)


def flag_transactions(txns: list[Transaction], statement: Statement) -> int:
    """Mutates txns: duplicates, outliers, round large amounts, balance breaks, negative balance, big cash."""
    for t in txns:
        t.is_flagged, t.flag_reason = False, None
    reasons: dict[int, list[str]] = defaultdict(list)

    seen: dict[tuple, int] = {}
    for i, t in enumerate(txns):
        key = (t.txn_date, t.debit, t.credit, (t.description or "")[:40].lower())
        if key in seen:
            reasons[i].append("Possible duplicate")
        else:
            seen[key] = i

    for side, attr in (("debit", "debit"), ("credit", "credit")):
        vals = [f(getattr(t, attr)) for t in txns if getattr(t, attr)]
        if len(vals) >= 12:
            mean, sd = statistics.mean(vals), statistics.pstdev(vals)
            limit = mean + 3 * sd
            for i, t in enumerate(txns):
                v = f(getattr(t, attr))
                if sd and v > limit and v > mean * 4:
                    reasons[i].append(f"Unusually large {side}")

    for i, t in enumerate(txns):
        amt = f(t.debit or t.credit)
        if amt >= 50000 and amt % 10000 == 0:
            reasons[i].append("Large round-figure amount")
        if t.category == "Cash Withdrawal" and amt >= 50000:
            reasons[i].append("Large cash withdrawal")
        if t.category == "Cash Deposit" and amt >= 200000 and statement.currency == "INR":
            reasons[i].append("Cash deposit >= 2,00,000 (Sec 269ST indicator)")
        if t.balance is not None and t.balance < 0:
            reasons[i].append("Negative balance")
        if not (t.description or "").strip():
            reasons[i].append("Missing description")

    prev = statement.opening_balance
    for i, t in enumerate(txns):
        if t.balance is not None and prev is not None:
            expected = prev + t.credit - t.debit
            if abs(expected - t.balance) > TOL:
                reasons[i].append(f"Running balance mismatch (expected {expected:,.2f})")
        if t.balance is not None:
            prev = t.balance

    n = 0
    for i, t in enumerate(txns):
        if reasons.get(i):
            t.is_flagged, t.flag_reason = True, "; ".join(dict.fromkeys(reasons[i]))[:255]
            n += 1
    return n


def build_summary(txns: list[Transaction], st: Statement) -> dict:
    deb = sum((t.debit for t in txns), ZERO)
    cre = sum((t.credit for t in txns), ZERO)
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO})
    cats: dict[str, dict] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO, "count": 0})
    for t in txns:
        key = t.txn_date.strftime("%Y-%m") if t.txn_date else "unknown"
        monthly[key]["debit"] += t.debit
        monthly[key]["credit"] += t.credit
        c = cats[t.category]
        c["debit"] += t.debit
        c["credit"] += t.credit
        c["count"] += 1
    top_debits = sorted([t for t in txns if t.debit], key=lambda t: t.debit, reverse=True)[:5]
    top_credits = sorted([t for t in txns if t.credit], key=lambda t: t.credit, reverse=True)[:5]

    check = {"status": "unknown", "detail": "Opening/closing balance not found - cannot reconcile."}
    if st.opening_balance is not None and st.closing_balance is not None:
        expected = st.opening_balance + cre - deb
        diff = expected - st.closing_balance
        ok = abs(diff) <= Decimal("1.00")
        check = {
            "status": "pass" if ok else "fail",
            "expected_closing": f(expected),
            "reported_closing": f(st.closing_balance),
            "difference": f(diff),
            "detail": "Opening + credits - debits equals closing balance." if ok else
            "Totals do not reconcile with the reported closing balance - some rows may be missing or mis-read.",
        }
    mismatches = sum(1 for t in txns if t.flag_reason and "balance mismatch" in t.flag_reason)

    def row(t: Transaction) -> dict:
        return {"date": t.txn_date.isoformat() if t.txn_date else None, "description": t.description, "debit": f(t.debit), "credit": f(t.credit)}

    return {
        "txn_count": len(txns),
        "total_debit": f(deb),
        "total_credit": f(cre),
        "net_movement": f(cre - deb),
        "avg_debit": f(deb / max(1, sum(1 for t in txns if t.debit))),
        "avg_credit": f(cre / max(1, sum(1 for t in txns if t.credit))),
        "monthly": [{"month": m, "debit": f(v["debit"]), "credit": f(v["credit"]), "net": f(v["credit"] - v["debit"])} for m, v in sorted(monthly.items())],
        "categories": sorted(
            [{"category": k, "debit": f(v["debit"]), "credit": f(v["credit"]), "count": v["count"]} for k, v in cats.items()],
            key=lambda x: x["debit"] + x["credit"], reverse=True,
        ),
        "top_debits": [row(t) for t in top_debits],
        "top_credits": [row(t) for t in top_credits],
        "balance_check": check,
        "balance_mismatches": mismatches,
        "flagged": sum(1 for t in txns if t.is_flagged),
        "uncategorized": sum(1 for t in txns if t.category == "Uncategorized"),
    }


def nature(head: str) -> str:
    return NATURE_BY_HEAD.get(head, "Transfer")
