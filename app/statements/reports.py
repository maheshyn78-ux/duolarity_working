"""Financial reports derived from a parsed bank statement (cash-basis, bank-derived)."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.statements.insights import f, nature
from app.statements.models import Statement, Transaction

ZERO = Decimal("0")
REPORT_TYPES = [
    "Trial Balance", "P&L Statement", "Balance Sheet", "Cash Flow", "GST Report", "Tax Review",
    "Audit Report", "Compliance Review", "Monthly Summary", "Category Breakdown",
]
SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}


def _indian(n: float) -> str:
    neg = n < 0
    s = f"{abs(n):.2f}"
    whole, dec = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts + [tail])
    return ("-" if neg else "") + whole + "." + dec


def money(n, cur: str) -> str:
    if n in (None, ""):
        return "-"
    n = float(n)
    sym = SYMBOL.get(cur, cur + " ")
    return sym + (_indian(n) if cur == "INR" else f"{n:,.2f}")


def build_report(kind: str, st: Statement, txns: list[Transaction]) -> dict:
    cur = st.currency or "INR"
    m = lambda x: money(x, cur)  # noqa: E731
    title = f"{kind} - {st.bank_name or st.filename}"
    notes: list[str] = []
    cols = ["Particulars", "Amount", "Status"]
    rows: list[list[str]] = []
    total: list[str] | None = None

    deb = sum((t.debit for t in txns), ZERO)
    cre = sum((t.credit for t in txns), ZERO)
    by_head: dict[str, dict[str, Decimal]] = defaultdict(lambda: {"debit": ZERO, "credit": ZERO})
    for t in txns:
        by_head[t.ledger_head]["debit"] += t.debit
        by_head[t.ledger_head]["credit"] += t.credit

    if kind == "Trial Balance":
        cols = ["Ledger", "Debit", "Credit"]
        opening = st.opening_balance if st.opening_balance is not None else ZERO
        closing = st.closing_balance if st.closing_balance is not None else opening + cre - deb
        rows.append(["Bank Account (closing balance)", m(closing) if closing >= 0 else "-", m(-closing) if closing < 0 else "-"])
        rows.append(["Opening balance b/f", "-", m(opening)] if opening >= 0 else ["Opening balance b/f", m(-opening), "-"])
        td = closing if closing >= 0 else ZERO
        tc = opening if opening >= 0 else ZERO
        if closing < 0:
            tc += -closing
        if opening < 0:
            td += -opening
        for head, v in sorted(by_head.items(), key=lambda kv: -(kv[1]["debit"] + kv[1]["credit"])):
            # money OUT of the bank is a debit to the expense/asset head; money IN is a credit to income/liability head
            d, c = v["debit"], v["credit"]
            rows.append([head, m(d) if d else "-", m(c) if c else "-"])
            td += d
            tc += c
        total = ["Total", m(td), m(tc)]
        notes.append("Bank-derived trial balance: bank closing balance + outflows (debit side) vs opening balance + inflows (credit side).")
        if abs(td - tc) > Decimal("1"):
            notes.append(f"Does not balance by {m(td - tc)} - statement totals don't reconcile with the reported opening/closing balances.")
    elif kind == "P&L Statement":
        inc: dict[str, Decimal] = defaultdict(lambda: ZERO)
        exp: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for head, v in by_head.items():
            n = nature(head)
            if n == "Income":
                inc[head] += v["credit"]
            elif n in ("Expense", "Tax"):
                exp[head] += v["debit"]
        rows.append(["INCOME", "", ""])
        for h, v in sorted(inc.items(), key=lambda kv: -kv[1]):
            if v:
                rows.append([h, m(v), "Income"])
        ti = sum(inc.values(), ZERO)
        rows.append(["Total income", m(ti), ""])
        rows.append(["EXPENSES", "", ""])
        for h, v in sorted(exp.items(), key=lambda kv: -kv[1]):
            if v:
                rows.append([h, m(v), "Expense"])
        te = sum(exp.values(), ZERO)
        rows.append(["Total expenses", m(te), ""])
        total = ["Net surplus / (deficit)", m(ti - te), "Surplus" if ti >= te else "Deficit"]
        notes.append("Cash-basis view from bank movements only. Transfers, investments, cash movements and loan principal are excluded.")
    elif kind == "Balance Sheet":
        cols = ["Item", "Amount", "Note"]
        opening = st.opening_balance or ZERO
        closing = st.closing_balance if st.closing_balance is not None else opening + cre - deb
        inv = by_head.get("Investments", {"debit": ZERO, "credit": ZERO})
        cash = by_head.get("Cash in Hand", {"debit": ZERO, "credit": ZERO})
        loans = by_head.get("Loan Repayments", {"debit": ZERO})
        rows += [
            ["ASSETS", "", ""],
            ["Bank balance (closing)", m(closing), "From statement"],
            ["Net investments made in period", m(inv["debit"] - inv["credit"]), "Outflows less redemptions"],
            ["Net cash withdrawn (cash in hand)", m(cash["debit"] - cash["credit"]), "ATM/cash less deposits"],
            ["LIABILITIES & EQUITY", "", ""],
            ["Loan repayments made in period", m(loans["debit"]), "Principal+interest, not split"],
            ["Opening balance (capital b/f)", m(opening), "From statement"],
        ]
        total = ["Net movement in period", m(cre - deb), ""]
        notes.append("A bank statement cannot show receivables, payables, fixed assets or accruals. This is an extract, not a full balance sheet.")
    elif kind == "Cash Flow":
        cols = ["Activity", "Inflow", "Outflow"]
        groups = {"Operating": ("Income", "Expense", "Tax"), "Investing": ("Asset",), "Financing": ("Liability",), "Transfers / Other": ("Transfer",)}
        tin = tout = ZERO
        for g, natures in groups.items():
            gi = go = ZERO
            for head, v in by_head.items():
                if nature(head) in natures:
                    gi += v["credit"]
                    go += v["debit"]
            rows.append([g, m(gi), m(go)])
            tin += gi
            tout += go
        total = ["Net cash flow", m(tin - tout), ""]
    elif kind in ("GST Report", "Tax Review"):
        is_gst = kind == "GST Report"
        pick = [t for t in txns if t.category == ("Tax - GST" if is_gst else "Tax - TDS") or (not is_gst and t.category in ("Tax - Income Tax", "Provident Fund / ESI"))]
        paid = sum((t.debit for t in pick), ZERO)
        rec = sum((t.credit for t in pick), ZERO)
        receipts = sum((t.credit for t in txns if nature(t.ledger_head) == "Income"), ZERO)
        rows.append([("GST" if is_gst else "Tax") + " payments identified", m(paid), f"{sum(1 for t in pick if t.debit)} txns"])
        rows.append([("GST" if is_gst else "TDS/Tax") + " credits / refunds identified", m(rec), f"{sum(1 for t in pick if t.credit)} txns"])
        if is_gst:
            rows.append(["Gross income receipts", m(receipts), ""])
            ind = receipts * Decimal(18) / Decimal(118)
            rows.append(["Indicative output GST @18% inclusive", m(ind), "Indicative only"])
            notes.append("Output GST is an indicative estimate; real liability depends on invoices, rates and ITC from the GST portal.")
        for t in pick[:25]:
            rows.append([f"{t.txn_date} {t.description[:60]}", m(t.debit or t.credit), "Debit" if t.debit else "Credit"])
        total = ["Net paid", m(paid - rec), ""]
    elif kind == "Audit Report":
        cols = ["Check", "Result", "Status"]
        bc = (st.summary_json or {}).get("balance_check", {})
        flagged = [t for t in txns if t.is_flagged]
        rows += [
            ["Statement reconciles (opening + credits - debits = closing)", bc.get("detail", "-"), {"pass": "OK", "fail": "Review"}.get(bc.get("status"), "N/A")],
            ["Running-balance breaks", str((st.summary_json or {}).get("balance_mismatches", 0)), "OK" if not (st.summary_json or {}).get("balance_mismatches") else "Review"],
            ["Possible duplicates", str(sum(1 for t in flagged if "duplicate" in (t.flag_reason or ""))), "OK" if not any("duplicate" in (t.flag_reason or "") for t in flagged) else "Review"],
            ["Unusually large transactions", str(sum(1 for t in flagged if "large" in (t.flag_reason or "").lower())), "Review" if any("large" in (t.flag_reason or "").lower() for t in flagged) else "OK"],
            ["Uncategorized transactions", str(sum(1 for t in txns if t.category == "Uncategorized")), "Review" if any(t.category == "Uncategorized" for t in txns) else "OK"],
        ]
        for t in flagged[:30]:
            rows.append([f"{t.txn_date} {t.description[:55]}", t.flag_reason or "", "Flagged"])
        total = ["Flagged transactions", str(len(flagged)), ""]
        notes.append("Automated analytical checks - not a substitute for a statutory audit.")
    elif kind == "Compliance Review":
        cols = ["Indicator", "Finding", "Status"]
        cash_big = [t for t in txns if t.category == "Cash Deposit" and t.credit >= 200000]
        cash_pay = [t for t in txns if t.category == "Cash Withdrawal" and t.debit > 10000]
        gst = [t for t in txns if t.category == "Tax - GST"]
        tds = [t for t in txns if t.category == "Tax - TDS"]
        rows += [
            ["GST payments found", f"{len(gst)} ({m(sum((t.debit for t in gst), ZERO))})", "OK" if gst else "None seen"],
            ["TDS entries found", f"{len(tds)}", "OK" if tds else "None seen"],
            ["Cash deposits >= 2,00,000 (Sec 269ST indicator)", str(len(cash_big)), "Review" if cash_big else "OK"],
            ["Cash withdrawals > 10,000 (Sec 40A(3) indicator)", str(len(cash_pay)), "Review" if cash_pay else "OK"],
            ["Uncategorized entries needing classification", str(sum(1 for t in txns if t.category == "Uncategorized")), "Review" if any(t.category == "Uncategorized" for t in txns) else "OK"],
        ]
        total = ["Items to review", str(sum(1 for r in rows if r[2] == "Review")), ""]
        notes.append("Heuristic indicators based on Indian rules; verify with the original documents and a qualified CA.")
    elif kind == "Monthly Summary":
        cols = ["Month", "Credits", "Debits"]
        mon: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
        for t in txns:
            k = t.txn_date.strftime("%b %Y") if t.txn_date else "Unknown"
            mon[k][0] += t.credit
            mon[k][1] += t.debit
        for k, (c, d) in mon.items():
            rows.append([k, m(c), m(d)])
        total = ["Total", m(cre), m(deb)]
    else:  # Category Breakdown
        cols = ["Category", "Debits", "Credits"]
        cats: dict[str, list[Decimal]] = defaultdict(lambda: [ZERO, ZERO])
        for t in txns:
            cats[t.category][0] += t.debit
            cats[t.category][1] += t.credit
        for k, (d, c) in sorted(cats.items(), key=lambda kv: -(kv[1][0] + kv[1][1])):
            rows.append([k, m(d) if d else "-", m(c) if c else "-"])
        total = ["Total", m(deb), m(cre)]

    return {"type": kind, "title": title, "columns": cols, "rows": rows, "total": total, "notes": notes, "currency": cur}
