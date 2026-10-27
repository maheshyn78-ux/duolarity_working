"""Generate sample bank statements (long PDF, CSV, XLSX) for testing:  python samples/make_samples.py"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).parent
random.seed(7)
NARR = [
    ("UPI/{n}/SWIGGY/Food", "d", (150, 900)), ("UPI/{n}/ZOMATO ORDER", "d", (120, 800)), ("NEFT CR-ACME TECH PVT LTD-SALARY", "c", (65000, 85000)),
    ("ATM WDL {n} MG ROAD BLR", "d", (2000, 20000)), ("BESCOM ELECTRICITY BILL {n}", "d", (900, 4200)), ("EMI HOME LOAN {n}", "d", (24500, 24500)),
    ("AMAZON PAY INDIA {n}", "d", (300, 6500)), ("INT.PD:{n}", "c", (120, 900)), ("NEFT CR-CLIENT INVOICE INV{n}", "c", (15000, 120000)),
    ("GST PAYMENT CHALLAN {n}", "d", (4000, 22000)), ("SMS ALERT CHARGES", "d", (17, 30)), ("UPI/{n}/RAHUL KUMAR/Rent", "d", (15000, 15000)),
    ("MUTUAL FUND SIP {n}", "d", (5000, 5000)), ("UBER INDIA {n}", "d", (120, 700)), ("CASH DEPOSIT CDM {n}", "c", (5000, 40000)),
]


def gen(n_rows=1200, opening=50000.00):
    bal, d, rows = opening, date(2024, 4, 1), []
    for _ in range(n_rows):
        d += timedelta(days=random.choice([0, 0, 1]))
        tpl, kind, (lo, hi) = random.choice(NARR)
        amt = round(random.uniform(lo, hi), 2)
        if kind == "d" and amt > bal:
            tpl, kind, (lo, hi) = NARR[2]
            amt = round(random.uniform(lo, hi), 2)
        bal = round(bal + amt if kind == "c" else bal - amt, 2)
        rows.append((d, tpl.format(n=random.randint(100000000, 999999999)), kind, amt, bal))
    return opening, rows


def inr(x):
    s = f"{x:,.2f}"  # western grouping is fine for the parser; make it Indian-style
    whole, dec = s.replace(",", "").split(".")
    if len(whole) > 3:
        h, t = whole[:-3], whole[-3:]
        parts = []
        while len(h) > 2:
            parts.insert(0, h[-2:]); h = h[:-2]
        if h: parts.insert(0, h)
        whole = ",".join(parts + [t])
    return f"{whole}.{dec}"


def pdf(opening, rows, path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    W, H = A4
    per_page = 38
    pages = (len(rows) + per_page - 1) // per_page
    for p in range(pages):
        c.setFont("Helvetica-Bold", 12)
        c.drawString(40, H - 40, "HDFC BANK LIMITED - Statement of Account")
        c.setFont("Helvetica", 9)
        c.drawString(40, H - 56, "Account Name: MAHESH Y N    Account No: 50100123456789    Currency: INR")
        c.drawString(40, H - 68, f"Page {p+1} of {pages}")
        c.drawString(40, H - 90, "Date        Narration                                         Withdrawal      Deposit        Balance")
        y = H - 106
        if p == 0:
            c.drawString(40, y, f"Opening Balance                                                                      {inr(opening)}"); y -= 14
        for d, narr, kind, amt, bal in rows[p * per_page:(p + 1) * per_page]:
            c.drawString(40, y, d.strftime("%d/%m/%Y"))
            c.drawString(100, y, narr[:46])
            c.drawRightString(400 if kind == "d" else 465, y, inr(amt))
            c.drawRightString(555, y, inr(bal))
            y -= 14
        if p == pages - 1:
            c.drawString(40, y - 6, f"Closing Balance                                                                      {inr(rows[-1][4])}")
        c.showPage()
    c.save()


if __name__ == "__main__":
    opening, rows = gen()
    pdf(opening, rows, OUT / "long_statement_32_pages.pdf")
    with open(OUT / "statement.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Txn Date", "Description", "Debit", "Credit", "Balance"])
        for d, n, k, a, b in rows[:300]:
            w.writerow([d.strftime("%d-%m-%Y"), n, a if k == "d" else "", a if k == "c" else "", b])
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["Date", "Particulars", "Withdrawals", "Deposits", "Balance"])
    for d, n, k, a, b in rows[:300]:
        ws.append([d, n, a if k == "d" else None, a if k == "c" else None, b])
    wb.save(OUT / "statement.xlsx")
    print("rows", len(rows), "opening", opening, "closing", rows[-1][4])
