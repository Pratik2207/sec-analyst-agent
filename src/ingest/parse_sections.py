"""Split a 10-K into Items (1, 1A, 7, 7A, 8) and then by subheading (FR-4). [track-a]

Output: data/processed/sections/<accession_no>.json. If Items can't be found, the whole
document is returned under item "full" and the failure is logged (X-4).

Output format (read only by src.ingest.chunker):
    {<manifest fields>, "fallback": bool,
     "items": {"1": {"heading": "Item 1. Business", "cross_reference": false,
                     "sections": [{"title": "Competition",
                                   "blocks": [{"type": "text" | "table", "text": "..."}]}]}}}
Tables are Markdown; "title" is "" for the text before an Item's first subheading.

How it works:
1. The HTML is flattened into blocks: text paragraphs (with bold/underline/font size)
   and tables. Layout tables (headings or bullets laid out in cells) become text blocks;
   data tables become Markdown (tables over MAX_TABLE_ROWS rows are dropped).
2. Page furniture (page numbers, "Table of Contents", running page headers) is dropped.
3. Every block starting with "Item <n>" is an Item heading candidate. For each Item the
   candidate followed by the most text wins, which skips the table of contents.
4. Annual-report-style 10-Ks (banks) often reduce Item 7 to "appears on pages 52-167";
   then the MD&A is located by its own heading elsewhere in the document.
5. Inside an Item, bold/underlined/larger-font short blocks start a new section.

Usage: uv run python -m src.ingest.parse_sections
"""

import json
import logging
import re
import warnings
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag, XMLParsedAsHTMLWarning

from config.settings import DATA_DIR, ROOT

SECTIONS_DIR = DATA_DIR / "processed" / "sections"

ITEMS = ("1", "1A", "7", "7A", "8")
REQUIRED_ITEMS = ("1", "1A", "7")
MAX_TABLE_ROWS = 30
MIN_ITEM_CHARS = 200        # an Item with less text than this is "not found"
STUB_MAX_CHARS = 1500       # Item 7 shorter than this that mentions pages = cross-reference
MAX_HEADING_CHARS = 600   # risk-factor titles can be a few sentences long

log = logging.getLogger(__name__)
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

BLOCK_TAGS = {"div", "p", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "center",
              "blockquote", "section", "article", "body", "html", "tr", "dl", "dt", "dd", "hr"}
SKIP_TAGS = {"head", "script", "style", "title", "ix:header"}

ITEM_RE = re.compile(r"^item\s*(\d{1,2}[a-c]?)\b\s*([.:\-—–])?\s*(.*)$", re.I | re.S)
PAGE_NUM_RE = re.compile(r"^(page\s*)?[\divxlc\-– ]{1,7}$", re.I)
MDNA_RE = re.compile(r"^management[’'`]?s discussion and analysis"
                     r"( of financial condition and results of operations)?\.?$", re.I)
MDNA_END_RE = re.compile(
    r"^(management[’'`]?s report on internal control|report of independent registered"
    r"|consolidated financial statements$|consolidated statements? of (income|operations|"
    r"earnings|financial condition))", re.I)
BULLETS = "•●◦▪·-–—*"
NUMERIC_CELL_RE = re.compile(r"^[$€£(]*\s*[\d.,]+\s*[)%]*$|^[—–-]$")
SENTENCE_END = ".!?:;\"”’)]"


@dataclass
class Block:
    kind: str                 # "text" | "table"
    text: str
    bold: bool = False
    underline: bool = False
    size: float | None = None
    furniture: bool = False


@dataclass(frozen=True)
class Style:
    bold: bool = False
    underline: bool = False
    size: float | None = None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()


def _apply_style(tag: Tag, st: Style) -> Style:
    bold, underline, size = st.bold, st.underline, st.size
    if tag.name in ("b", "strong", "h1", "h2", "h3", "h4", "h5", "h6"):
        bold = True
    elif tag.name == "u":
        underline = True
    css = (tag.get("style") or "").lower()
    if css:
        if m := re.search(r"font-weight:\s*(\w+)", css):
            w = m.group(1)
            bold = w in ("bold", "bolder") or (w.isdigit() and int(w) >= 600)
        if m := re.search(r"text-decoration[\w-]*:\s*([^;]+)", css):
            underline = "underline" in m.group(1)
        if m := re.search(r"font-size:\s*([\d.]+)\s*(pt|px)", css):
            size = float(m.group(1)) * (0.75 if m.group(2) == "px" else 1.0)
    return Style(bold, underline, size)


def _hidden(tag: Tag) -> bool:
    return tag.name in SKIP_TAGS or "display:none" in (tag.get("style") or "").replace(" ", "")


class _Flattener:
    """Walks the DOM once and emits a flat list of Blocks."""

    def __init__(self):
        self.blocks: list[Block] = []
        self.buf: list[tuple[str, Style]] = []

    def flush(self) -> None:
        parts, self.buf = self.buf, []
        text = _norm("".join(t for t, _ in parts))
        if not text:
            return
        weights = [(len(t.strip()), s) for t, s in parts if t.strip()]
        total = sum(w for w, _ in weights)
        sizes = Counter()
        for w, s in weights:
            if s.size:
                sizes[s.size] += w
        self.blocks.append(Block(
            "text", text,
            bold=all(s.bold for _, s in weights),
            underline=all(s.underline for _, s in weights),
            size=sizes.most_common(1)[0][0] if sizes and total else None,
        ))

    def walk(self, node: Tag, st: Style) -> None:
        for child in node.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                self.buf.append((str(child), st))
                continue
            if not isinstance(child, Tag) or _hidden(child):
                continue
            cst = _apply_style(child, st)
            if child.name == "table":
                self.flush()
                self.table(child, cst)
            elif child.name == "br":
                self.buf.append((" ", st))
            elif child.name in BLOCK_TAGS:
                self.flush()
                self.walk(child, cst)
                self.flush()
            else:
                self.walk(child, cst)

    def table(self, table: Tag, st: Style) -> None:
        rows = [r for r in table.find_all("tr") if r.find_parent("table") is table]
        grid = [[_norm(c.get_text(" ")) for c in r.find_all(["td", "th"], recursive=False)]
                for r in rows]
        content = [[c for c in row if c] for row in grid]
        content = [row for row in content if row]
        if not content:
            return
        if _is_layout_table(content):
            for r in rows:   # each row is one text block, keeping its styles
                for cell in r.find_all(["td", "th"], recursive=False):
                    self.walk(cell, _apply_style(cell, _apply_style(r, st)))
                    self.buf.append((" ", st))
                self.flush()
            return
        if len(content) > MAX_TABLE_ROWS:
            return
        self.blocks.append(Block("table", _markdown_table(grid)))


def _is_marker(cell: str) -> bool:
    return len(cell) <= 4 and (cell[0] in BULLETS or bool(re.fullmatch(r"\(?\w{1,2}[.)]", cell)))


def _is_layout_table(rows: list[list[str]]) -> bool:
    """Headings, bullets, footnotes and page footers laid out in table cells (not data)."""
    if len(rows) == 1:
        return True
    for row in rows:
        cells = [c for c in row if not _is_marker(c)]
        if len(cells) > 2 or any(NUMERIC_CELL_RE.match(c) for c in cells):
            return False
        if len(cells) == 2 and len(rows) > 2:
            return False
    return True


def _merge_fragments(cells: list[str]) -> list[str]:
    """Join '$' with the number after it, and ')' / '%' with the number before it."""
    out: list[str] = []
    pending = ""
    for c in cells:
        if c in ("$", "€", "£", "("):
            pending += c
            continue
        if c and c[0] in ")%" and len(c) <= 3 and out:
            out[-1] += c
            continue
        out.append(pending + c if c else pending)
        pending = ""
    if pending:
        out.append(pending)
    return out


def _markdown_table(grid: list[list[str]]) -> str:
    rows = []
    for row in grid:
        if not any(row):
            continue
        cells = _merge_fragments(row)
        rows.append([cells[0]] + [c for c in cells[1:] if c])  # keep the label column
    width = max(len(r) for r in rows)
    lines = []
    for i, r in enumerate(rows):
        r = [c.replace("|", "\\|") for c in r] + [""] * (width - len(r))
        lines.append("| " + " | ".join(r) + " |")
        if i == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def html_to_blocks(html: bytes | str) -> list[Block]:
    soup = BeautifulSoup(html, "lxml")
    flat = _Flattener()
    flat.walk(soup.body or soup, Style())
    flat.flush()
    _mark_furniture(flat.blocks)
    return flat.blocks


def _mark_furniture(blocks: list[Block]) -> None:
    """Page numbers, 'Table of Contents' links and running page headers/footers."""
    def key(t: str) -> str:   # "Pfizer Inc. 2024 Form 10-K 15" repeats with other numbers
        return re.sub(r"\d+", "#", t)

    counts = Counter(key(b.text) for b in blocks if b.kind == "text" and len(b.text) < 100)
    for b in blocks:
        if b.kind != "text":
            continue
        t = b.text
        if (PAGE_NUM_RE.match(t) or t.lower() in ("table of contents", "index")
                or (len(t) < 100 and counts[key(t)] >= 10 and not ITEM_RE.match(t))):
            b.furniture = True


def _item_key(b: Block) -> str | None:
    if b.kind != "text" or b.furniture or len(b.text) > 200:
        return None
    m = ITEM_RE.match(b.text)
    if not m:
        return None
    _, punct, rest = m.groups()
    if rest and not punct and not rest[0].isupper():
        return None   # "Item 7 of this report ..." is a sentence, not a heading
    return m.group(1).upper()


def _content_chars(blocks: list[Block], start: int, end: int) -> int:
    return sum(len(b.text) for b in blocks[start:end] if not b.furniture)


def find_items(blocks: list[Block]) -> dict[str, dict]:
    """Map item -> {start, end, heading, cross_reference} (block index range of the body)."""
    cands = [(i, k) for i, b in enumerate(blocks) if (k := _item_key(b))]
    items: dict[str, dict] = {}
    for n, (i, key) in enumerate(cands):
        if key not in ITEMS:
            continue
        end = cands[n + 1][0] if n + 1 < len(cands) else len(blocks)
        chars = _content_chars(blocks, i + 1, end)
        if key not in items or chars > items[key]["chars"]:
            items[key] = {"start": i + 1, "end": end, "chars": chars,
                          "heading": blocks[i].text, "cross_reference": False}
    if "7" in items:
        _resolve_mdna_reference(blocks, items["7"], [i for i, _ in cands])
    return {k: v for k, v in items.items() if v["chars"] >= MIN_ITEM_CHARS}


def _resolve_mdna_reference(blocks: list[Block], item: dict, cand_idx: list[int]) -> None:
    """Item 7 that only says "MD&A appears on pages 52-167": find the MD&A by its heading."""
    stub = " ".join(b.text for b in blocks[item["start"]:item["end"]])
    if item["chars"] >= STUB_MAX_CHARS or not re.search(r"\bpages?\b", stub, re.I):
        return
    start = next((i for i in range(item["end"], len(blocks))
                  if blocks[i].kind == "text" and MDNA_RE.match(blocks[i].text)), None)
    if start is None:
        return
    cand_set = set(cand_idx)
    end = next((i for i in range(start + 1, len(blocks))
                if i in cand_set or (blocks[i].kind == "text" and len(blocks[i].text) < 120
                                          and MDNA_END_RE.match(blocks[i].text))), len(blocks))
    chars = _content_chars(blocks, start + 1, end)
    if chars > item["chars"]:
        item.update(start=start + 1, end=end, chars=chars, cross_reference=True)


def body_font_size(blocks: list[Block]) -> float | None:
    sizes = Counter()
    for b in blocks:
        if b.kind == "text" and b.size:
            sizes[b.size] += len(b.text)
    return sizes.most_common(1)[0][0] if sizes else None


def is_heading(b: Block, body_size: float | None) -> bool:
    t = b.text
    if b.kind != "text" or len(t) > MAX_HEADING_CHARS or t[0] in BULLETS:
        return False
    if not any(c.isalpha() for c in t):
        return False
    if b.bold or b.underline:
        return True
    return bool(body_size and b.size and b.size >= body_size + 1.5 and len(t) <= 150)


def _continues(prev: str, nxt: str) -> bool:
    """A paragraph cut by a page break: no closing punctuation, next starts lowercase."""
    return prev[-1] not in SENTENCE_END and nxt[0].islower()


def split_sections(blocks: list[Block], body_size: float | None) -> list[dict]:
    sections: list[dict] = []
    cur: dict = {"title": "", "blocks": []}
    for b in blocks:
        if b.furniture:
            continue
        if is_heading(b, body_size):
            if cur["blocks"]:
                sections.append(cur)
            cur = {"title": b.text, "blocks": []}   # consecutive headings: the last one wins
        elif b.kind == "table":
            cur["blocks"].append({"type": "table", "text": b.text})
        else:
            last = cur["blocks"][-1] if cur["blocks"] else None
            if last and last["type"] == "text" and _continues(last["text"], b.text):
                last["text"] += " " + b.text
            else:
                cur["blocks"].append({"type": "text", "text": b.text})
    if cur["blocks"]:
        sections.append(cur)
    return sections


def parse_html(html: bytes | str, accession_no: str = "?") -> dict:
    """Return {"fallback": bool, "items": {item: {heading, cross_reference, sections}}}."""
    blocks = html_to_blocks(html)
    body_size = body_font_size(blocks)
    found = find_items(blocks)
    missing = [k for k in REQUIRED_ITEMS if k not in found]
    if missing:
        log.warning("%s: Items %s not found; using the whole document as item 'full'",
                    accession_no, ", ".join(missing))
        return {"fallback": True, "items": {"full": {
            "heading": "", "cross_reference": False,
            "sections": split_sections(blocks, body_size)}}}
    items = {}
    for key in ITEMS:
        if key in found:
            it = found[key]
            items[key] = {"heading": it["heading"], "cross_reference": it["cross_reference"],
                          "sections": split_sections(blocks[it["start"]:it["end"]], body_size)}
    return {"fallback": False, "items": items}


def parse_filing(record: dict) -> dict:
    path = Path(record["path"])
    html = (path if path.is_absolute() else ROOT / path).read_bytes()
    return {**record, **parse_html(html, record["accession_no"])}


def main() -> None:
    from src.ingest.download_filings import MANIFEST

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    SECTIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    for rec in records:
        parsed = parse_filing(rec)
        out = SECTIONS_DIR / f"{rec['accession_no']}.json"
        out.write_text(json.dumps(parsed, ensure_ascii=False), encoding="utf-8")
        summary = ", ".join(f"{k}:{len(v['sections'])}" for k, v in parsed["items"].items())
        log.info("%s FY%s %s -> %s%s", rec["ticker"], rec["fiscal_year"], rec["accession_no"],
                 summary, " (fallback)" if parsed["fallback"] else "")


if __name__ == "__main__":
    main()
