import random
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SAMPLES = Path(__file__).resolve().parents[2] / "samples"
sys.path.insert(0, str(SAMPLES))
import make_samples as ms  # noqa: E402


@pytest.fixture(scope="module")
def client():
    from app.main import create_app

    with TestClient(create_app()) as c:
        r = c.post("/api/v1/auth/register", json={"email": "t@example.com", "password": "Passw0rd!x", "full_name": "Test User"})
        assert r.status_code == 201, r.text
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        yield c


def _wait(client, sid, timeout=120):
    t = time.time()
    while time.time() - t < timeout:
        d = client.get(f"/api/v1/statements/{sid}").json()
        if d["status"] in ("completed", "failed"):
            return d
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_long_pdf_end_to_end(client):
    random.seed(7)
    _, rows = ms.gen()
    with open(SAMPLES / "long_statement_32_pages.pdf", "rb") as f:
        r = client.post("/api/v1/statements", files={"file": ("long.pdf", f, "application/pdf")})
    assert r.status_code == 202
    d = _wait(client, r.json()["id"])
    assert d["status"] == "completed", d.get("error")
    assert d["txn_count"] == len(rows) == 1200
    assert d["summary"]["balance_check"]["status"] == "pass"
    assert d["bank_name"] == "HDFC Bank"
    assert d["pages_total"] == 32
    sid = d["id"]
    tx = client.get(f"/api/v1/statements/{sid}/transactions", params={"page_size": 50}).json()
    assert tx["total"] == 1200 and len(tx["items"]) == 50
    for kind in ("Trial Balance", "P&L Statement", "Balance Sheet", "Cash Flow", "GST Report", "Audit Report", "Compliance Review"):
        rep = client.get(f"/api/v1/statements/{sid}/report", params={"type": kind}).json()
        assert rep["rows"], kind
    tb = client.get(f"/api/v1/statements/{sid}/report", params={"type": "Trial Balance"}).json()
    assert not any("Does not balance" in n for n in tb["notes"])
    assert client.get(f"/api/v1/statements/{sid}/export?format=xlsx").status_code == 200
    assert client.get(f"/api/v1/statements/{sid}/export?format=csv").text.count("\n") > 1000
    ans = client.post("/api/v1/ai/chat", json={"message": "what is my closing balance?", "statement_id": sid}).json()
    assert "closing balance" in ans["answer"].lower()
    ans = client.post("/api/v1/ai/chat", json={"message": "how much did I spend on swiggy", "statement_id": sid}).json()
    assert "matching" in ans["answer"].lower()


def test_csv_and_xlsx(client):
    for name in ("statement.csv", "statement.xlsx"):
        with open(SAMPLES / name, "rb") as f:
            r = client.post("/api/v1/statements", files={"file": (name, f, "application/octet-stream")})
        d = _wait(client, r.json()["id"])
        assert d["status"] == "completed" and d["txn_count"] == 300, d.get("error")
        assert d["method"] == "table"


def test_rejects_bad_files(client):
    r = client.post("/api/v1/statements", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 415
    r = client.post("/api/v1/statements", files={"file": ("e.csv", b"", "text/csv")})
    assert r.status_code == 400
    r = client.post("/api/v1/statements", files={"file": ("junk.txt", b"hello world nothing here", "text/plain")})
    d = _wait(client, r.json()["id"])
    assert d["status"] == "failed" and "No transactions" in d["error"]


def test_llm_fallback_for_odd_layout(client, monkeypatch):
    """A layout the rules can't read is handed to the (mocked) local LLM in chunks."""
    from app.ai import llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    calls = {"n": 0}

    def fake_json(msgs, max_tokens=None):
        calls["n"] += 1
        user = msgs[-1]["content"]
        if "Statement text" in user:
            return {"transactions": [{"date": "2025-01-05", "description": "Coffee shop", "debit": 120.5, "credit": 0, "balance": 879.5},
                                     {"date": "2025-01-06", "description": "Client payment", "debit": 0, "credit": 500, "balance": 1379.5}]}
        return {"items": []}

    monkeypatch.setattr(llm, "chat_json", fake_json)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: "Mock summary.")
    odd = "Jan 5th - paid the coffee shop one twenty fifty\nJan 6th - client sent five hundred\n" * 3
    r = client.post("/api/v1/statements", files={"file": ("odd.txt", odd.encode(), "text/plain")})
    d = _wait(client, r.json()["id"])
    assert d["status"] == "completed", d.get("error")
    assert d["method"] == "llm" and d["txn_count"] == 2 and calls["n"] >= 1
    assert d["ai_summary"] == "Mock summary."
