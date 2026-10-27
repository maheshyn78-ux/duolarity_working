"""Rule-based categorization into ledger heads (LLM refines whatever stays 'Uncategorized')."""
from __future__ import annotations

import re

# (category, ledger_head, nature, regex, applies_to) ; applies_to: 'debit' | 'credit' | 'any'
RULES: list[tuple[str, str, str, str, str]] = [
    ("Salary", "Salary Income", "Income", r"\b(salary|sal cr|payroll|wages credit)\b", "credit"),
    ("Salaries & Wages", "Salaries & Wages", "Expense", r"\b(salary|payroll|wages|stipend)\b", "debit"),
    ("Interest Income", "Interest Income", "Income", r"\b(int\.?\s*pd|interest\s*(paid|credit|cr|capitali[sz]ed)|int\s*cr|sb\s*int|savings\s*interest)\b", "credit"),
    ("Dividend", "Other Income", "Income", r"\b(dividend|div\s*cr)\b", "credit"),
    ("Refund", "Refunds & Reversals", "Income", r"\b(refund|reversal|reversed|cashback|chargeback)\b", "credit"),
    ("Tax - GST", "Taxes & Statutory", "Tax", r"\b(gst|cgst|sgst|igst|gstin|gstn)\b", "debit"),
    ("Tax - TDS", "Taxes & Statutory", "Tax", r"\b(tds|tax deducted)\b", "any"),
    ("Tax - Income Tax", "Taxes & Statutory", "Tax", r"\b(income\s*tax|advance\s*tax|itd|cbdt|challan|oltas|self assessment tax)\b", "debit"),
    ("Provident Fund / ESI", "Taxes & Statutory", "Tax", r"\b(epf|pf\s*contribution|esic|esi\b|provident)\b", "debit"),
    ("Bank Charges", "Bank Charges", "Expense", r"\b(charges?|chgs?|fee|sms\s*alert|amc|annual\s*maintenance|min(imum)?\s*bal|penalty|processing\s*fee|debit card\s*fee|service tax)\b", "debit"),
    ("Loan / EMI", "Loan Repayments", "Liability", r"\b(emi|loan|ecs\s*emi|nach.*(loan|finance)|bajaj\s*fin|hdfc\s*ltd|home\s*loan|car\s*loan|repayment)\b", "debit"),
    ("Loan Received", "Loans & Borrowings", "Liability", r"\b(loan\s*(disb|credit)|disbursement)\b", "credit"),
    ("Insurance", "Insurance Premium", "Expense", r"\b(insurance|lic\b|premium|policybazaar|star\s*health|hdfc\s*life|icici\s*pru|max\s*life)\b", "debit"),
    ("Investments", "Investments", "Asset", r"\b(mutual\s*fund|\bsip\b|zerodha|groww|upstox|kuvera|coin\b|nps\b|ppf\b|fd\s*(booking|creation)|fixed\s*deposit|rd\s*instal|stock|demat|angel\s*(one|broking))\b", "debit"),
    ("Investment Redemption", "Investments", "Asset", r"\b(redemption|mf\s*redeem|fd\s*(maturity|closure)|maturity)\b", "credit"),
    ("Rent", "Rent", "Expense", r"\b(rent|lease|landlord)\b", "debit"),
    ("Utilities", "Utilities", "Expense", r"\b(electricity|bescom|msedcl|tneb|water\s*bill|gas\s*bill|piped\s*gas|indane|bharat\s*gas|broadband|airtel|jio\b|vodafone|\bvi\b|bsnl|act\s*fibernet|recharge|postpaid|dth|tata\s*(play|sky)|bill\s*desk|billdesk)\b", "debit"),
    ("Food & Dining", "Food & Dining", "Expense", r"\b(swiggy|zomato|restaurant|cafe|dominos|domino|mcdonald|kfc|pizza|starbucks|bakery|hotel|dining|eats|blinkit|zepto|bigbasket|big\s*basket|dmart|grocer|supermarket|instamart)\b", "debit"),
    ("Travel & Fuel", "Travel & Fuel", "Expense", r"\b(uber|ola\b|rapido|irctc|makemytrip|goibibo|redbus|indigo|air\s*india|vistara|spicejet|petrol|diesel|fuel|hpcl|bpcl|iocl|indian\s*oil|shell|fastag|toll|metro|namma)\b", "debit"),
    ("Shopping", "Shopping", "Expense", r"\b(amazon|flipkart|myntra|ajio|meesho|nykaa|croma|reliance\s*(retail|digital)|lifestyle|pantaloons|decathlon|ikea)\b", "debit"),
    ("Subscriptions", "Subscriptions", "Expense", r"\b(netflix|spotify|hotstar|prime\s*video|youtube|apple|google\s*(play|one|cloud)|microsoft|adobe|github|openai|chatgpt|canva|notion|zoom|aws|azure)\b", "debit"),
    ("Healthcare", "Healthcare", "Expense", r"\b(hospital|clinic|pharma|medical|medplus|apollo|1mg|pharmeasy|netmeds|diagnostic|lab\b|dental|doctor)\b", "debit"),
    ("Education", "Education", "Expense", r"\b(school|college|university|tuition|exam\s*fee|coursera|udemy|byju|unacademy|vtu|fees?\s*(pay|college))\b", "debit"),
    ("Professional Fees", "Professional Fees", "Expense", r"\b(consult|professional\s*fee|legal|audit\s*fee|ca\s*fee|advocate|freelance)\b", "debit"),
    ("Cash Withdrawal", "Cash in Hand", "Asset", r"\b(atm|cash\s*(wdl|withdrawal)|nwd|cwdr|self\s*(cheque|chq)|cash\s*paid)\b", "debit"),
    ("Cash Deposit", "Cash in Hand", "Asset", r"\b(cash\s*(dep|deposit)|cdm|bna\s*dep|by\s*cash)\b", "credit"),
    ("Business Receipts", "Sales / Receipts", "Income", r"\b(invoice|inv\s*no|sales|customer\s*pay|payment\s*received|receipt|rtgs\s*cr|neft\s*cr|from\s*(client|customer))\b", "credit"),
    ("Business Payments", "Purchases / Vendor Payments", "Expense", r"\b(vendor|supplier|purchase|inv\s*no|invoice|payment\s*to)\b", "debit"),
    ("UPI Transfer", "Fund Transfers", "Transfer", r"\bupi\b", "any"),
    ("NEFT/IMPS/RTGS", "Fund Transfers", "Transfer", r"\b(neft|imps|rtgs|ift|fund\s*transfer|trf|transfer)\b", "any"),
    ("Cheque", "Cheques", "Transfer", r"\b(chq|cheque|clg|clearing)\b", "any"),
]
_COMPILED = [(c, h, n, re.compile(rx, re.I), a) for c, h, n, rx, a in RULES]

NATURE_BY_HEAD = {h: n for _, h, n, _, _ in RULES}
NATURE_BY_HEAD["Uncategorized"] = "Transfer"
NATURE_BY_HEAD["Other Income"] = "Income"
NATURE_BY_HEAD["Other Expenses"] = "Expense"
CATEGORIES = sorted({c for c, *_ in RULES} | {"Other Income", "Other Expenses", "Uncategorized"})
HEAD_BY_CATEGORY = {c: h for c, h, *_ in RULES}
HEAD_BY_CATEGORY.update({"Other Income": "Other Income", "Other Expenses": "Other Expenses", "Uncategorized": "Uncategorized"})


def categorize(description: str, is_credit: bool) -> tuple[str, str] | None:
    side = "credit" if is_credit else "debit"
    for cat, head, _n, rx, applies in _COMPILED:
        if applies in ("any", side) and rx.search(description or ""):
            return cat, head
    return None


def head_for(category: str) -> str:
    return HEAD_BY_CATEGORY.get(category, "Uncategorized")
