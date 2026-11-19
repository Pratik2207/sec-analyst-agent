"""Phase 4 contract: turning tool results into evidence for prompts, finding numbers in
text, and turning cited source ids into Citations. Owned by the main session.

Evidence items carry the source_id the answer writer must cite. Calculation items carry
"input_source_ids" (the facts they used); citing a calc:<n> id resolves to those filings.
Filing text is untrusted data: render_evidence escapes "<" so a chunk cannot close the
evidence block or fake another item.
"""

import re
from dataclasses import dataclass, field

from src.api.schemas import Citation
from src.tools.types import ToolResult


@dataclass
class EvidenceItem:
    source_id: str
    kind: str
    text: str
    numbers: list[float] = field(default_factory=list)


def _fmt_value(v: float) -> str:
    return f"{v:,.2f}".rstrip("0").rstrip(".")


def evidence_items(tool_results: list[ToolResult]) -> list[EvidenceItem]:
    items: list[EvidenceItem] = []
    for res in tool_results:
        if not res.ok:
            continue
        for d in res.data:
            sid = d.get("source_id", "")
            if "metric" in d and "value" in d:           # a financial fact row
                text = (f"{d.get('ticker')} FY{d.get('fiscal_year')} {d['metric']} = "
                        f"{_fmt_value(d['value'])} USD"
                        + (f" (period ending {d['period_end']})" if d.get("period_end") else ""))
                items.append(EvidenceItem(sid, "fact", text, [float(d["value"])]))
            elif "result" in d and "expression" in d:   # a calculation
                who = f"{d['ticker']} " if d.get("ticker") else ""
                label = d.get("name") or "result"
                # Small models misread the sign of a change; state the direction in words.
                way = (f", {direction(d['result'])}"
                       if is_change(label, d["expression"]) else "")
                text = f"{who}{label} = {d['result']:.6g}{way} (computed: {d['expression']})"
                items.append(EvidenceItem(sid, "calc", text, [float(d["result"])]))
            elif "text" in d:                            # a chunk or a section
                head = (f"{d.get('ticker', '')} FY{d.get('fiscal_year', '')} "
                        f"Item {d.get('item', '')}")
                items.append(EvidenceItem(sid, "text", f"{head}: {d['text']}",
                                          numbers_in(d["text"])))
            elif "ticker" in d:                          # list_companies rows etc.
                text = ", ".join(f"{k}={v}" for k, v in d.items() if k != "source_id")
                items.append(EvidenceItem(sid, "info", text))
    return items


_CHANGE_NAME = re.compile(r"chang|diff|delta|growth|grow|increase|decrease|yoy", re.I)
_YEAR_VAR = re.compile(r"_((?:19|20)\d\d)\b")


def is_change(name: str, expression: str) -> bool:
    """A calc is a change when its name says so, or it subtracts values of two years."""
    years = set(_YEAR_VAR.findall(expression or ""))
    return bool(_CHANGE_NAME.search(name or "")) or (len(years) >= 2 and "-" in expression)


def direction(value: float) -> str:
    return "increased" if value > 0 else "decreased" if value < 0 else "unchanged"


def render_evidence(items: list[EvidenceItem]) -> str:
    """Evidence block for prompts. "<" in content is escaped (filing text is data)."""
    out = ["<evidence>"]
    for it in items:
        out.append(f'<item id="{it.source_id}">{it.text.replace("<", "&lt;")}</item>')
    out.append("</evidence>")
    return "\n".join(out)


# ---- numbers --------------------------------------------------------------------------

_NUM = re.compile(r"(?<![\w.])[-−]?\(?\$?\(?\d[\d,]*(?:\.\d+)?\)?\s*"
                  r"(%|percent|trillion|billion|million|thousand|bn|mn|[kmb]\b)?", re.I)
_SCALE = {"trillion": 1e12, "billion": 1e9, "bn": 1e9, "b": 1e9, "million": 1e6, "mn": 1e6,
          "m": 1e6, "thousand": 1e3, "k": 1e3}
_YEARISH = re.compile(r"^(19|20)\d\d$")
_ISO_DATE = re.compile(r"\b(?:19|20)\d\d-\d\d-\d\d\b")


def strip_computed(text: str) -> str:
    """Remove "(computed: ...)" copied from calc evidence, including nested parentheses."""
    while (i := text.find("(computed:")) != -1:
        depth, j = 0, i
        for j in range(i, len(text)):
            depth += {"(": 1, ")": -1}.get(text[j], 0)
            if depth == 0:
                break
        text = (text[:i].rstrip() + text[j + 1:]).strip()
    return text


def numbers_in(text: str) -> list[float]:
    """Numbers stated in text, scaled ($16.55 billion -> 16.55e9; 75.0% -> 75.0).
    Bare 4-digit years (2024, FY2025), ISO dates (2025-01-26) and item numbers are skipped."""
    out = []
    text = _ISO_DATE.sub(" ", text)
    for m in _NUM.finditer(text):
        raw = m.group(0)
        unit = (m.group(1) or "").lower()
        digits = re.sub(r"[^\d.]", "", raw.split()[0] if unit else raw)
        if not digits or digits == ".":
            continue
        if not unit and "$" not in raw and _YEARISH.match(digits):
            continue
        try:
            v = float(digits)
        except ValueError:
            continue
        v *= _SCALE.get(unit, 1.0)
        if raw.strip().startswith(("-", "−", "(")):   # (1.2) accounting negative
            v = -v
        out.append(v)
    return out


def number_matches(claimed: float, source: float, rel_tol: float = 0.006) -> bool:
    """Does a number stated in a claim match a source number "within rounding"? Accepts
    the same quantity at a different scale (16.55 vs 16_546_000_000 when the claim's unit
    was dropped) and percent vs fraction (75.0 vs 0.75)."""
    for s in (source, source / 1e3, source / 1e6, source / 1e9, source / 1e12, source * 100):
        if s == 0:
            if claimed == 0:
                return True
            continue
        if abs(claimed - s) <= max(abs(s) * rel_tol, 0.0051):
            return True
    return False


# ---- citations ------------------------------------------------------------------------

def _index(tool_results: list[ToolResult]) -> tuple[dict, dict]:
    sources, items = {}, {}
    for res in tool_results:
        for s in res.sources:
            sources[s.source_id] = s
        for d in res.data:
            if d.get("source_id"):
                items.setdefault(d["source_id"], d)
    return sources, items


def resolve(source_ids: list[str], tool_results: list[ToolResult]) -> list[Citation]:
    """Citations for the cited ids; a calc id resolves to the filings of its inputs.
    Unknown ids and non-filing sources are dropped. Order kept, duplicates removed."""
    sources, items = _index(tool_results)
    out: list[Citation] = []

    def add(sid: str, depth: int = 0) -> None:
        src = sources.get(sid)
        if src is not None and src.kind == "calc" and depth < 3:
            for inner in items.get(sid, {}).get("input_source_ids", []):
                add(inner, depth + 1)
            return
        cite = src.citation() if src is not None else None
        if cite is not None and cite not in out:
            out.append(cite)

    for sid in source_ids:
        add(sid)
    return out


def render_answer(claims: list, tool_results: list[ToolResult]) -> tuple[str, list[Citation]]:
    """Answer text with [n] markers after each claim, and the numbered citation list."""
    citations: list[Citation] = []
    sentences = []
    for c in claims:
        marks = []
        for cite in resolve(c.source_ids, tool_results):
            if cite not in citations:
                citations.append(cite)
            marks.append(citations.index(cite) + 1)
        text = c.text.rstrip()
        if marks:
            tag = " " + "".join(f"[{n}]" for n in marks)
            text = text[:-1] + tag + text[-1] if text[-1:] in ".!?" else text + tag
        sentences.append(text)
    return " ".join(sentences), citations
