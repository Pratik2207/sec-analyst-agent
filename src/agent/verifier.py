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
            # "decreased by 4.34 points" states the magnitude of a -4.34 change; the
            # direction itself is checked separately (direction_conflict)
            out.extend([float(d["result"]), abs(float(d["result"]))])
            if depth < 3:
                for inner in d.get("input_source_ids", []):
                    out.extend(_pool(inner, items, depth + 1))
        elif "text" in d:
            out.extend(numbers_in(d["text"]))
    return out


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".")


def _unsupported(text: str, cited: list[str], items: dict[str, list[dict]]) -> list[float]:
    pool = [v for sid in cited for v in _pool(sid, items)]
    return [n for n in checked_numbers(text) if not any(number_matches(n, v) for v in pool)]


def _stated_in(bad: list[float], cited: list[str], items: dict[str, list[dict]],
               among: set[str] | None = None) -> list[str]:
    """Uncited ids (within `among` if given) whose own numbers include some of `bad`. Calc
    inputs are not expanded, so a ratio points to its calc and a raw value to its filing."""
    return [sid for sid in items if sid not in cited and (among is None or sid in among)
            and any(number_matches(n, v) for n in bad for v in _pool(sid, items, depth=3))][:4]


def stated_in(text: str, source_ids: list[str], tool_results: list[ToolResult],
              among: set[str]) -> list[str]:
    """Ids in `among` that state numbers of `text` which its cited `source_ids` do not
    (used by the answer writer to repair citations)."""
    items, _ = _index(tool_results)
    bad = _unsupported(text, source_ids, items)
    return _stated_in(bad, source_ids, items, among) if bad else []


# ---- direction check (Phase 4 integration finding) ------------------------------------
# A claim like "NVDA raised R&D as a share of revenue" states no number, so the number check
# can't catch it; the 4B answer model misread negative change calcs as increases. For every
# company the claim names, a clause that says up/down about a quantity must agree with the
# sign of that company's change calc for the quantity.

_UP = re.compile(r"\b(rais\w*|increas\w*|rose|rise[sn]?|grew|grow\w*|higher|expand\w*|"
                 r"improv\w*|up)\b", re.I)
_DOWN = re.compile(r"\b(fell|fall\w*|decreas\w*|declin\w*|lower\w*|drop\w*|down|"
                   r"shr[ai]nk\w*|contract\w*|reduc\w*)\b", re.I)
_CLAUSE = re.compile(r",|;|:|\.\s|\bbut\b|\bwhile\b|\bwhereas\b|\bwith\b|\band\b", re.I)
_GENERIC = {"change", "chg", "diff", "delta", "growth", "yoy", "pct", "percent", "of", "to",
            "vs", "increase", "decrease", "the", "a"}
_TOKEN_RE = {"rd": r"r\s*&\s*d|research|\brd\b", "pct": r"%|percent"}


def _companies() -> dict[str, re.Pattern]:
    from config.settings import load_companies  # local import: config is cheap, avoids cycles
    out = {}
    for c in load_companies():
        alts = [re.escape(c["ticker"])] + ([re.escape(c["name"])] if c.get("name") else [])
        out[c["ticker"]] = re.compile(r"\b(" + "|".join(alts) + r")\b")
    return out


def _quantity_matches(name: str, clause: str) -> bool:
    tokens = [t for t in re.split(r"[_\W]+", name.lower()) if t and t not in _GENERIC
              and not re.fullmatch(r"\d+", t)]
    return bool(tokens) and all(
        re.search(_TOKEN_RE.get(t, r"\b" + re.escape(t)), clause, re.I) for t in tokens)


def direction_conflict(text: str, items: dict[str, list[dict]]) -> str | None:
    from src.agent.evidence import direction, is_change

    companies = _companies()
    named = [t for t, pat in companies.items() if pat.search(text)]
    if not named:
        return None
    changes = [d for rows in items.values() for d in rows
               if "result" in d and d.get("ticker") in named
               and is_change(d.get("name") or "", d.get("expression") or "")]
    for clause in _CLAUSE.split(text):
        up, down = bool(_UP.search(clause)), bool(_DOWN.search(clause))
        if up == down:        # no direction word, or both: nothing to check
            continue
        said = "increased" if up else "decreased"
        # A clause is about the companies it names; a clause naming none inherits the
        # claim's company only when the claim names exactly one ("Gross margin fell only for
        # QCOM" must not be checked against AMD named elsewhere in the claim).
        subjects = [t for t in named if companies[t].search(clause)] or (
            named if len(named) == 1 else [])
        for d in changes:
            if d["ticker"] in subjects and _quantity_matches(d["name"], clause) and direction(
                    d["result"]) not in (said, "unchanged"):
                return (f"{d['ticker']} {d['name']} = {d['result']:.4g} "
                        f"({direction(d['result'])}), but the claim says it {said}")
    return None


def _check(claim: Claim, items: dict[str, list[dict]], known: set[str]) -> str | None:
    """None if the claim passes, else a short reason."""
    if not claim.source_ids:
        return "cites no source"
    unknown = [s for s in claim.source_ids if s not in known]
    if unknown:
        return f"cites unknown source id(s): {', '.join(unknown)}"
    conflict = direction_conflict(claim.text, items)
    if conflict:
        return conflict
    bad = _unsupported(claim.text, claim.source_ids, items)
    if not bad:
        return None
    pool = [v for sid in claim.source_ids for v in _pool(sid, items)]
    has = ", ".join(_fmt(v) for v in list(dict.fromkeys(pool))[:5]) or "no numbers"
    more = ", ..." if len(set(pool)) > 5 else ""
    reason = (f"{', '.join(_fmt(n) for n in bad)} not found in cited "
              f"{', '.join(claim.source_ids)} (has {has}{more})")
    elsewhere = _stated_in(bad, claim.source_ids, items)
    if elsewhere:
        reason += f"; stated in {', '.join(elsewhere)}"
    return reason


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
