"""Deterministic (no-AI) bank statement parsing: amounts, dates, text lines, tables.

This is the fast path. It handles the vast majority of digital bank PDFs/CSVs/XLSX.
When it can't make sense of a document, the LLM extractor (app.ai.extract_llm) takes over.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

ZERO = Decimal("0")

# ----------------------------------------------------------------------------- amounts
_MONEY = re.compile(
    r"""(?<![\w./-])
        (?P<neg>-|\()?\s*
        (?:₹|Rs\.?|INR|\$|USD|€|£)?\s*
        (?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+\.\d{1,2}|\d{1,3}(?:,\d{3})+)
        \)?\s*
        (?P<drcr>Cr\.?|Dr\.?|CR|DR)?
        (?![\w/-])""",
    re.X,
)
_MONEY_RELAXED = re.compile(
    r"(?<![\w./-])(?P<neg>-|\()?\s*(?P<num>\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?)\)?\s*(?P<drcr>Cr\.?|Dr\.?|CR|DR)?(?![\w/-])"
)


@dataclass
class Money:
    value: Decimal
    drcr: str | None  # 'Cr' | 'Dr' | None
    neg: bool
    start: int
    end: int


def to_decimal(text: str) -> Decimal | None:
    t = (text or "").strip()
    if not t or t in {"-", "--", "—", "NA", "N/A", "nil", "Nil"}:
        return None
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    drcr = None
    m = re.search(r"(Cr|Dr|CR|DR)\.?\s*$", t)
    if m:
        drcr = m.group(1).title()
    t = re.sub(r"(Cr|Dr|CR|DR)\.?\s*$", "", t)
    t = re.sub(r"[^\d.]", "", t.replace(",", ""))
    if not t or t == ".":
        return None
    try:
        v = Decimal(t)
    except InvalidOperation:
        return None
    return -v if neg else v


def find_money(line: str, relaxed: bool = False) -> list[Money]:
    rx = _MONEY_RELAXED if relaxed else _MONEY
    out: list[Money] = []
    for m in rx.finditer(line):
        raw = m.group("num")
        try:
            v = Decimal(raw.replace(",", ""))
        except InvalidOperation:
            continue
        out.append(
            Money(
                value=v,
                drcr=(m.group("drcr") or "").rstrip(".").title() or None,
                neg=bool(m.group("neg")),
                start=m.start(),
                end=m.end(),
            )
        )
    return out


# ----------------------------------------------------------------------------- dates
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_MON = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
DATE_PATTERNS = [
    re.compile(r"(?<![\d/.-])(?P<d>\d{1,2})[/\-.](?P<m>\d{1,2})[/\-.](?P<y>\d{4}|\d{2})(?!\d)"),
    re.compile(r"(?<!\d)(?P<y>\d{4})[/\-.](?P<m>\d{1,2})[/\-.](?P<d>\d{1,2})(?!\d)"),
    re.compile(rf"(?P<d>\d{{1,2}})[ \-/,.]*(?P<mon>{_MON})[ \-/,.]*(?P<y>\d{{4}}|\d{{2}})(?!\d)", re.I),
    re.compile(rf"(?P<mon>{_MON})[ \-.]+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?[ \-.]+(?P<y>\d{{4}})(?!\d)", re.I),
]
LEADING_DATE = [re.compile(r"^\s*" + p.pattern, p.flags) for p in DATE_PATTERNS]


def _mk_date(d: int, m: int, y: int) -> date | None:
    if y < 100:
        y += 2000 if y < 70 else 1900
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _from_match(m: re.Match, dayfirst: bool) -> date | None:
    g = m.groupdict()
    y = int(g["y"])
    if g.get("mon"):
        mon = _MONTHS.get(g["mon"][:3].lower())
        return _mk_date(int(g["d"]), mon, y) if mon else None
    a, b = int(g["d"]), int(g["m"])
    # the 2nd pattern (yyyy-mm-dd) names groups d/m already in the right order
    if len(g["y"]) == 4 and m.re is DATE_PATTERNS[1]:
        return _mk_date(a, b, y)
    if dayfirst:
        return _mk_date(a, b, y) or _mk_date(b, a, y)
    return _mk_date(b, a, y) or _mk_date(a, b, y)


def parse_date(text: str, dayfirst: bool = True) -> date | None:
    if not text:
        return None
    t = str(text).strip()
    if isinstance(text, (datetime, date)):
        return text.date() if isinstance(text, datetime) else text
    for p in DATE_PATTERNS:
        m = p.search(t)
        if m:
            d = _from_match(m, dayfirst)
            if d:
                return d
    return None


def match_leading_date(line: str, dayfirst: bool) -> tuple[date, int] | None:
    for rx in LEADING_DATE:
        m = rx.match(line)
        if m:
            d = _from_match(m, dayfirst)
            if d:
                return d, m.end()
    return None


def detect_dayfirst(pages: list[str]) -> bool:
    """Look at numeric dates: a first component >12 means day-first; a second >12 means month-first."""
    day_first = month_first = 0
    rx = DATE_PATTERNS[0]
    for page in pages[:10]:
        for m in rx.finditer(page):
            a, b = int(m.group("d")), int(m.group("m"))
            if a > 12 >= b:
                day_first += 1
            elif b > 12 >= a:
                month_first += 1
    if month_first > day_first:
        return False
    return True


# ----------------------------------------------------------------------------- text → transactions
@dataclass
class RawTxn:
    date: date | None
    description: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    balance: Decimal | None = None
    reference: str | None = None
    page: int | None = None
    amount: Decimal | None = None  # unsigned amount when direction is still unknown
    direction: str | None = None  # 'debit' | 'credit' | None
    drcr_balance: str | None = None


@dataclass
class ParseResult:
    txns: list[RawTxn] = field(default_factory=list)
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    dated_lines: int = 0
    meta: dict = field(default_factory=dict)


_SKIP = re.compile(
    r"^\s*(page\s*\d+(\s*(of|/)\s*\d+)?|statement of account|account statement|date\s+(narration|description|particulars|details|transaction)|"
    r"txn\s*date|tran\s*date|value\s*date|sl\.?\s*no|s\.?\s*no\.?\s|this is a computer generated|registered office|"
    r"toll free|www\.|customer care|end of statement|\*+\s*end)",
    re.I,
)
_OPEN = re.compile(r"(opening|brought\s*forward|b/?f\b|balance\s*b/?f|previous\s*balance|beginning\s*balance)", re.I)
_CLOSE = re.compile(r"(closing\s*balance|carried\s*forward|c/?f\b|ending\s*balance|balance\s*c/?f|final\s*balance)", re.I)
_TOTALS = re.compile(r"^\s*(total|grand\s*total|sub\s*total|statement summary|summary|transaction total)\b", re.I)

CREDIT_HINT = re.compile(
    r"\b(cr|credit(ed)?|deposit|salary|sal\b|interest\s*(paid|credit|cr)|refund|reversal|cashback|int\.?pd|received|by\s+(clg|transfer)|inward|neft\s*cr|imps\s*cr|upi\s*cr|rtgs\s*cr|dividend)\b",
    re.I,
)
DEBIT_HINT = re.compile(
    r"\b(dr|debit(ed)?|withdraw(al)?|atm|wdl|pos\b|purchase|charges?|fee|emi|paid|payment\s+to|to\s+(transfer|self)|outward|neft\s*dr|imps\s*dr|upi\s*dr|nach\s*dr|chq\s*paid|cheque\s*paid|bill\s*pay|sip|gst|tds)\b",
    re.I,
)


def _normalize_line(line: str) -> str:
    return re.sub(r"\d", "#", re.sub(r"\s+", " ", line.strip().lower()))


def strip_repeated_lines(pages: list[str]) -> list[list[str]]:
    """Split pages into lines and drop lines that repeat on many pages (running headers/footers)."""
    split = [[ln.rstrip() for ln in p.splitlines() if ln.strip()] for p in pages]
    if len(pages) < 4:
        return split
    seen: Counter[str] = Counter()
    for lines in split:
        for n in {_normalize_line(l) for l in lines}:
            seen[n] += 1
    threshold = max(3, int(len(pages) * 0.5))
    repeated = {n for n, c in seen.items() if c >= threshold}
    cleaned: list[list[str]] = []
    for lines in split:
        keep = []
        for l in lines:
            n = _normalize_line(l)
            # never drop lines that start with a date (could be a legitimate repeated txn)
            if n in repeated and not re.match(r"^\s*[\d#]{1,4}[/\-.][\d#]{1,2}[/\-.][\d#]{2,4}", n):
                continue
            keep.append(l)
        cleaned.append(keep)
    return cleaned


def parse_text_pages(pages: list[str], dayfirst: bool | None = None) -> ParseResult:
    """Parse statement text (one string per page) into raw transactions."""
    if dayfirst is None:
        dayfirst = detect_dayfirst(pages)
    res = ParseResult()
    page_lines = strip_repeated_lines(pages)

    # Pass 1 uses strict money regex (needs decimals/grouping); if almost nothing parses, retry relaxed.
    for relaxed in (False, True):
        res = _parse_lines(page_lines, dayfirst, relaxed)
        if len(res.txns) >= 3 or relaxed:
            break
    _resolve_directions(res)
    return res


def _parse_lines(page_lines: list[list[str]], dayfirst: bool, relaxed: bool) -> ParseResult:
    res = ParseResult()
    current: RawTxn | None = None
    prev_balance: Decimal | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            current.description = re.sub(r"\s{2,}", " ", current.description).strip(" -|:")
            res.txns.append(current)
            current = None

    for pno, lines in enumerate(page_lines, start=1):
        for line in lines:
            if _SKIP.match(line):
                continue
            dated = match_leading_date(line, dayfirst)
            if not dated:
                # opening / closing balance lines (undated)
                if _OPEN.search(line) and not _CLOSE.search(line):
                    mm = find_money(line, relaxed)
                    if mm and res.opening_balance is None:
                        res.opening_balance = _signed_balance(mm[-1])
                        prev_balance = res.opening_balance
                    continue
                if _CLOSE.search(line):
                    mm = find_money(line, relaxed)
                    if mm:
                        res.closing_balance = _signed_balance(mm[-1])
                    continue
                if _TOTALS.match(line):
                    flush()
                    continue
                # continuation of previous transaction narration
                if current is not None and not find_money(line, relaxed) and len(line.strip()) < 160:
                    current.description += " " + line.strip()
                elif current is not None:
                    # a continuation line that carries the amounts (wrapped rows)
                    mm = find_money(line, relaxed)
                    if mm and current.amount is None and current.balance is None:
                        _assign_amounts(current, mm)
                        current.description += " " + _strip_money(line, mm).strip()
                continue

            d, end = dated
            rest = line[end:]
            # optional second (value) date directly after the first
            second = match_leading_date(rest.lstrip(), dayfirst)
            if second and rest.lstrip() != rest or (second and rest[:1] in " \t"):
                rest = rest.lstrip()[second[1]:]
            res.dated_lines += 1
            if _OPEN.search(rest) and not _CLOSE.search(rest):
                mm = find_money(rest, relaxed)
                if mm:
                    res.opening_balance = _signed_balance(mm[-1])
                    prev_balance = res.opening_balance
                continue
            if _CLOSE.search(rest) and not find_money(rest, relaxed):
                continue
            flush()
            mm = find_money(rest, relaxed)
            txn = RawTxn(date=d, description="", page=pno)
            if mm:
                _assign_amounts(txn, mm)
                txn.description = _strip_money(rest, mm).strip()
            else:
                txn.description = rest.strip()
            ref = re.search(r"\b(?:chq|cheque|ref|utr|rrn)[\s.#:no]*([A-Z0-9]{6,})\b", txn.description, re.I)
            if ref:
                txn.reference = ref.group(1)[:120]
            current = txn
    flush()
    # drop rows without any amount (headers etc.)
    res.txns = [t for t in res.txns if t.amount is not None or t.debit or t.credit]
    return res


def _signed_balance(m: Money) -> Decimal:
    v = m.value
    if m.neg or m.drcr == "Dr":
        v = -v
    return v


def _assign_amounts(txn: RawTxn, mm: list[Money]) -> None:
    """Last number is the running balance when there are 2+ numbers."""
    nums = mm[-3:]
    if len(nums) >= 3:
        w, dep, bal = nums[-3], nums[-2], nums[-1]
        txn.balance = _signed_balance(bal)
        txn.drcr_balance = bal.drcr
        if w.value and not dep.value:
            txn.amount, txn.direction = w.value, "debit"
        elif dep.value and not w.value:
            txn.amount, txn.direction = dep.value, "credit"
        else:
            txn.amount = w.value or dep.value
    elif len(nums) == 2:
        amt, bal = nums
        txn.amount = amt.value
        txn.balance = _signed_balance(bal)
        txn.drcr_balance = bal.drcr
        if amt.drcr == "Dr" or amt.neg:
            txn.direction = "debit"
        elif amt.drcr == "Cr":
            txn.direction = "credit"
    elif len(nums) == 1:
        amt = nums[0]
        txn.amount = amt.value
        if amt.drcr == "Dr" or amt.neg:
            txn.direction = "debit"
        elif amt.drcr == "Cr":
            txn.direction = "credit"


def _strip_money(line: str, mm: list[Money]) -> str:
    out, last = [], 0
    for m in mm:
        out.append(line[last : m.start])
        last = m.end
    out.append(line[last:])
    return " ".join(x.strip() for x in out if x.strip())


def _hint_direction(desc: str) -> str | None:
    c, d = bool(CREDIT_HINT.search(desc)), bool(DEBIT_HINT.search(desc))
    if c and not d:
        return "credit"
    if d and not c:
        return "debit"
    return None


def _resolve_directions(res: ParseResult) -> None:
    """Use running balances to decide debit vs credit; fall back to DR/CR markers and keywords."""
    txns = res.txns
    tol = Decimal("0.02")
    prev = res.opening_balance
    for i, t in enumerate(txns):
        if t.amount is None:
            continue
        if t.balance is not None and prev is not None:
            delta = t.balance - prev
            if abs(delta - t.amount) <= tol:
                t.direction = "credit"
            elif abs(delta + t.amount) <= tol:
                t.direction = "debit"
        if t.balance is not None:
            prev = t.balance
    # unresolved: try backwards using next txn's balance (works for the very first row)
    for i, t in enumerate(txns):
        if t.direction or t.amount is None or t.balance is None:
            continue
        if i + 1 < len(txns):
            n = txns[i + 1]
            if n.balance is not None and n.amount is not None:
                delta = n.balance - t.balance
                if abs(abs(delta) - n.amount) <= tol:
                    pass  # next row consistent; try this row against opening implied by itself
        # try both hypotheses against the following row's implied starting balance
        if i + 1 < len(txns) and txns[i + 1].balance is not None and txns[i + 1].amount is not None:
            n = txns[i + 1]
            start_n_credit = n.balance - n.amount
            start_n_debit = n.balance + n.amount
            if abs(start_n_credit - t.balance) <= tol or abs(start_n_debit - t.balance) <= tol:
                implied_prev_c = t.balance - t.amount  # if t were a credit, the prior balance
                implied_prev_d = t.balance + t.amount
                if res.opening_balance is not None:
                    if abs(implied_prev_c - res.opening_balance) <= tol:
                        t.direction = "credit"
                    elif abs(implied_prev_d - res.opening_balance) <= tol:
                        t.direction = "debit"
    for t in txns:
        if t.amount is None:
            continue
        if not t.direction:
            t.direction = _hint_direction(t.description) or "debit"
        if t.direction == "credit":
            t.credit, t.debit = abs(t.amount), ZERO
        else:
            t.debit, t.credit = abs(t.amount), ZERO
    # infer opening balance from first transaction when missing
    if res.opening_balance is None and txns and txns[0].balance is not None:
        first = txns[0]
        res.opening_balance = first.balance - first.credit + first.debit
    if res.closing_balance is None:
        for t in reversed(txns):
            if t.balance is not None:
                res.closing_balance = t.balance
                break


# ----------------------------------------------------------------------------- tables (CSV / XLSX / pdf tables)
HEADER_WORDS = {
    "date": ("date", "txn date", "transaction date", "tran date", "posting date", "value date", "trans date", "booking date"),
    "desc": ("narration", "description", "particulars", "details", "transaction details", "remarks", "transaction remarks", "memo", "payee"),
    "ref": ("chq", "cheque", "ref", "reference", "utr", "txn id", "transaction id", "instrument"),
    "debit": ("debit", "withdrawal", "withdrawals", "dr", "paid out", "money out", "withdrawal amt", "debit amount", "withdrawal amount"),
    "credit": ("credit", "deposit", "deposits", "cr", "paid in", "money in", "deposit amt", "credit amount", "deposit amount"),
    "amount": ("amount", "txn amount", "transaction amount"),
    "balance": ("balance", "closing balance", "running balance", "bal", "available balance"),
    "type": ("type", "dr/cr", "cr/dr", "txn type", "transaction type"),
}


def _header_map(row: list[str]) -> dict[str, int] | None:
    cells = [re.sub(r"[^a-z/ ]", "", (c or "").lower()).strip() for c in row]
    mapping: dict[str, int] = {}
    for key, words in HEADER_WORDS.items():
        for idx, c in enumerate(cells):
            if not c or idx in mapping.values():
                continue
            if any(c == w or (len(w) > 3 and w in c) for w in words):
                mapping[key] = idx
                break
    if "date" in mapping and ("debit" in mapping or "credit" in mapping or "amount" in mapping):
        return mapping
    return None


def parse_table_rows(rows: list[list[str]], dayfirst: bool | None = None, page: int | None = None) -> ParseResult:
    """Parse rows of cells (CSV/XLSX/pdf tables). Finds the header row automatically."""
    res = ParseResult()
    if dayfirst is None:
        dayfirst = detect_dayfirst([" ".join(str(c) for c in r if c) for r in rows[:200]])
    mapping: dict[str, int] | None = None
    for r in rows:
        cells = [("" if c is None else str(c)).strip() for c in r]
        if not any(cells):
            continue
        hm = _header_map(cells)
        if hm:
            mapping = hm
            continue
        if not mapping:
            continue
        get = lambda k: cells[mapping[k]] if k in mapping and mapping[k] < len(cells) else ""  # noqa: E731
        d = parse_date(get("date"), dayfirst) if get("date") else None
        desc = get("desc")
        if not d:
            if desc and res.txns and not any(get(k) for k in ("debit", "credit", "amount")):
                res.txns[-1].description += " " + desc  # wrapped narration row
            elif _OPEN.search(" ".join(cells)):
                bal = to_decimal(get("balance"))
                if bal is not None and res.opening_balance is None:
                    res.opening_balance = bal
            continue
        res.dated_lines += 1
        debit, credit = to_decimal(get("debit")), to_decimal(get("credit"))
        amount = to_decimal(get("amount"))
        txn = RawTxn(date=d, description=desc, reference=(get("ref") or None), page=page)
        txn.balance = to_decimal(get("balance"))
        if debit or credit:
            txn.debit, txn.credit = abs(debit or ZERO), abs(credit or ZERO)
            txn.amount = txn.debit or txn.credit
            txn.direction = "debit" if txn.debit else "credit"
        elif amount is not None:
            kind = get("type").lower()
            txn.amount = abs(amount)
            if kind.startswith(("dr", "d", "w")) or amount < 0:
                txn.direction = "debit"
            elif kind.startswith(("cr", "c", "dep")):
                txn.direction = "credit"
        else:
            continue
        res.txns.append(txn)
    _resolve_directions(res)
    # rebuild debit/credit for rows whose direction was pre-set
    for t in res.txns:
        if t.direction == "debit" and not t.debit:
            t.debit, t.credit = abs(t.amount or ZERO), ZERO
        elif t.direction == "credit" and not t.credit:
            t.credit, t.debit = abs(t.amount or ZERO), ZERO
    return res


# ----------------------------------------------------------------------------- metadata
BANKS = [
    "HDFC Bank", "ICICI Bank", "State Bank of India", "Axis Bank", "Kotak Mahindra Bank", "Canara Bank", "Punjab National Bank",
    "Bank of Baroda", "Yes Bank", "IDFC FIRST Bank", "IndusInd Bank", "Union Bank of India", "Federal Bank", "Bank of India",
    "Indian Bank", "Central Bank of India", "UCO Bank", "IDBI Bank", "Karnataka Bank", "South Indian Bank", "RBL Bank",
    "Bandhan Bank", "AU Small Finance Bank", "Paytm Payments Bank", "Chase", "Bank of America", "Wells Fargo", "Citibank",
    "HSBC", "Barclays", "Lloyds", "NatWest", "Santander", "Capital One", "TD Bank", "Standard Chartered", "Deutsche Bank",
]
_BANK_ALIASES = {"SBI": "State Bank of India", "PNB": "Punjab National Bank", "BOB": "Bank of Baroda", "KOTAK": "Kotak Mahindra Bank"}


def extract_metadata(pages: list[str], txns: list[RawTxn]) -> dict:
    head = "\n".join(pages[:2])[:6000]
    meta: dict = {}
    low = head.lower()
    for b in BANKS:
        if b.lower() in low or b.lower().replace(" bank", "") in low.split("\n")[0:8].__str__().lower():
            meta["bank_name"] = b
            break
    if "bank_name" not in meta:
        for k, v in _BANK_ALIASES.items():
            if re.search(rf"\b{k}\b", head, re.I):
                meta["bank_name"] = v
                break
    m = re.search(r"(?:a/?c|account)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([Xx*\d][Xx*\d\- ]{5,22}\d)", head, re.I)
    if m:
        acct = re.sub(r"\s+", "", m.group(1))
        meta["account_number"] = ("*" * max(0, len(acct) - 4)) + acct[-4:]
    m = re.search(r"(?:account\s*(?:holder|name)|customer\s*name|name\s*of\s*(?:the\s*)?customer|a/?c\s*name|name)\s*[:\-]\s*([A-Za-z][A-Za-z .&'-]{2,60})", head, re.I)
    if m:
        name = re.split(r"\s+(?:Account|A/c|Acct|Customer|Cust|Currency|IFSC|Branch|PAN|Statement|Period|Date)\b", m.group(1).strip(), maxsplit=1, flags=re.I)[0]
        meta["account_holder"] = name.strip().rstrip(".") or None
    sym = head + " " + " ".join(p[:2000] for p in pages[:1])
    if re.search(r"₹|\bINR\b|\bRs\.?\b", sym):
        meta["currency"] = "INR"
    elif "$" in sym or re.search(r"\bUSD\b", sym):
        meta["currency"] = "USD"
    elif "€" in sym or re.search(r"\bEUR\b", sym):
        meta["currency"] = "EUR"
    elif "£" in sym or re.search(r"\bGBP\b", sym):
        meta["currency"] = "GBP"
    return meta
