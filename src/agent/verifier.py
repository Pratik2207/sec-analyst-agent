"""Verifier (FR-13): code only, no LLM. [track-b]

verify(draft: Draft, tool_results: list[ToolResult]) -> VerifyResult
A claim passes when every number it states (Claim.numbers) matches, via
evidence.number_matches, a number in at least one of its cited sources (fact values,
calc results, numbers in cited chunk/section text; a calc id also counts its input
facts). Claims citing unknown ids fail. Reasons are short and specific so they can be fed
back to the answer writer.

Choices:
- The numbers checked are re-read from the claim text with evidence.numbers_in, so the
  check covers exactly what the user will read (Claim.numbers is filled the same way).
- Label rule: a bare integer 0-99 written without "$", "%", a decimal point, a thousands
  separator, a sign or a scale word ("Item 7", "3 companies", "top 5", "Item 1A") is a
  label or a count, not a reported value, and is not checked. "$7", "7%", "7.0",
  "7 billion" are checked.
- A claim with no source ids fails ("cites no source").
"""

import re

from src.agent.evidence import number_matches, numbers_in
from src.agent.state import Claim, Draft, VerifyResult
from src.tools.types import ToolResult

_LABEL = re.compile(
    r"(?<![\w.,$\-−(])(\d{1,2})[A-Ca-c]?(?![\d%]|[.,]\d)"
    r"(?!\s*(?:percent|trillion|billion|million|thousand|bn|mn|[kmb]\b))", re.I)


def checked_numbers(text: str) -> list[float]:
    """numbers_in(text) minus label integers (see the label rule above)."""
    nums = numbers_in(text)
    for m in _LABEL.finditer(text):
        v = float(m.group(1))
        if v in nums:
            nums.remove(v)
    return nums


def _index(tool_results: list[ToolResult]) -> tuple[dict[str, list[dict]], set[str]]:
    items: dict[str, list[dict]] = {}
    known: set[str] = set()
    for res in tool_results:
        if not res.ok:
            continue
        known.update(s.source_id for s in res.sources)
        for d in res.data:
            if d.get("source_id"):
                items.setdefault(d["source_id"], []).append(d)
                known.add(d["source_id"])
    return items, known


def _pool(sid: str, items: dict[str, list[dict]], depth: int = 0) -> list[float]:
    """Numbers a claim may state when it cites `sid`."""
    out: list[float] = []
    for d in items.get(sid, []):
        if "metric" in d and "value" in d:
            out.append(float(d["value"]))
        elif "result" in d and "expression" in d:
            out.append(float(d["result"]))
            if depth < 3:
                for inner in d.get("input_source_ids", []):
                    out.extend(_pool(inner, items, depth + 1))
        elif "text" in d:
            out.extend(numbers_in(d["text"]))
    return out


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _check(claim: Claim, items: dict[str, list[dict]], known: set[str]) -> str | None:
    """None if the claim passes, else a short reason."""
    if not claim.source_ids:
        return "cites no source"
    unknown = [s for s in claim.source_ids if s not in known]
    if unknown:
        return f"cites unknown source id(s): {', '.join(unknown)}"
    pool = [v for sid in claim.source_ids for v in _pool(sid, items)]
    bad = [n for n in checked_numbers(claim.text)
           if not any(number_matches(n, v) for v in pool)]
    if not bad:
        return None
    has = ", ".join(_fmt(v) for v in list(dict.fromkeys(pool))[:5]) or "no numbers"
    more = ", ..." if len(set(pool)) > 5 else ""
    return (f"{', '.join(_fmt(n) for n in bad)} not found in cited "
            f"{', '.join(claim.source_ids)} (has {has}{more})")


def verify(draft: Draft, tool_results: list[ToolResult]) -> VerifyResult:
    result = VerifyResult()
    items, known = _index(tool_results)
    for claim in draft.claims:
        reason = _check(claim, items, known)
        if reason is None:
            result.ok_claims.append(claim)
        else:
            result.failed_claims.append((claim, reason))
    return result


def feedback_text(result: VerifyResult) -> str:
    """The rejected claims and their reasons, as `answer(..., feedback=...)` expects."""
    return "\n".join(f'- "{c.text}" (cited {", ".join(c.source_ids) or "nothing"}): {reason}'
                     for c, reason in result.failed_claims)
