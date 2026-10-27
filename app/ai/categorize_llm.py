"""Ask the local LLM to classify transactions the rules couldn't. Batched + de-duplicated by description."""
from __future__ import annotations

import logging
import re
from collections.abc import Callable

from app.ai import llm
from app.statements.categorize import CATEGORIES

log = logging.getLogger(__name__)
BATCH = 40
MAX_UNIQUE = 600


def _key(desc: str, credit: bool) -> str:
    return ("C|" if credit else "D|") + re.sub(r"\d+", "#", desc.lower())[:120]


def classify(items: list[tuple[str, bool]], progress: Callable[[int, int], None] | None = None) -> dict[str, str]:
    """items: (description, is_credit). Returns {key: category}."""
    uniq: dict[str, tuple[str, bool]] = {}
    for d, c in items:
        uniq.setdefault(_key(d, c), (d, c))
    keys = list(uniq)[:MAX_UNIQUE]
    result: dict[str, str] = {}
    cats = ", ".join(CATEGORIES)
    for b in range(0, len(keys), BATCH):
        part = keys[b : b + BATCH]
        lines = [f'{i}. [{"CREDIT" if uniq[k][1] else "DEBIT"}] {uniq[k][0][:140]}' for i, k in enumerate(part)]
        msgs = [
            {"role": "system", "content": "You classify bank transactions for an accountant. Reply JSON only: "
             '{"items":[{"i":0,"category":"..."}]}. category MUST be exactly one of: ' + cats + ". Use 'Uncategorized' if unsure."},
            {"role": "user", "content": "\n".join(lines)},
        ]
        try:
            data = llm.chat_json(msgs)
            for it in (data.get("items", []) if isinstance(data, dict) else []):
                idx, cat = it.get("i"), str(it.get("category", ""))
                if isinstance(idx, int) and 0 <= idx < len(part) and cat in CATEGORIES and cat != "Uncategorized":
                    result[part[idx]] = cat
        except llm.LLMUnavailable:
            raise
        except Exception as e:
            log.warning("LLM categorize batch failed: %s", e)
        if progress:
            progress(min(b + BATCH, len(keys)), len(keys))
    return result


key_for = _key
