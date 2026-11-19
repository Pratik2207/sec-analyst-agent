"""Retrieval recall@10.

A retrieved chunk payload is a hit for a question when it matches one gold source's ticker,
fiscal_year and item (when the gold source gives one) and its text contains every
gold_contains phrase (case-insensitive, whitespace-normalised). A question is recalled when
any of its top-10 payloads is a hit. Only questions with gold_contains are scored.
"""

import re

from evals.schema import DatasetItem


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def is_hit(payload: dict, item: DatasetItem) -> bool:
    text = _norm(payload.get("text", ""))
    if not all(_norm(p) in text for p in item.gold_contains):
        return False
    for g in item.gold_sources:
        if (str(payload.get("ticker", "")).upper() == g.ticker.upper()
                and int(payload.get("fiscal_year", 0)) == g.fiscal_year
                and (g.item is None or str(payload.get("item")) == g.item)):
            return True
    return False


def first_hit_rank(payloads: list[dict], item: DatasetItem, k: int = 10) -> int | None:
    """1-based rank of the first hit in the top k, or None."""
    for i, p in enumerate(payloads[:k], 1):
        if is_hit(p, item):
            return i
    return None
