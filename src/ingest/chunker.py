"""Build chunks with context headers and metadata (FR-5, PRD 7.1). [track-a]

Reads data/processed/sections/*.json, writes chunk_schema.CHUNKS_DIR/<accession_no>.jsonl
(records exactly matching chunk_schema.Chunk).

One chunk per section (risk factor, MD&A subheading, ...) when it fits, one chunk per
small table. Larger text is split at paragraph, then sentence, then word boundaries into
pieces of about chunk_min_tokens..chunk_max_tokens with about chunk_overlap overlap.
Every chunk's token_count (header included) is <= chunk_max_tokens.

Usage: uv run python -m src.ingest.chunker
"""

import json
import logging
import re
from pathlib import Path

from config.settings import get_settings
from src.ingest.chunk_schema import (
    CHUNKS_DIR,
    FALLBACK_ITEM,
    TEXT_ITEMS,
    Chunk,
    count_tokens,
    make_header,
    write_chunks,
)
from src.ingest.parse_sections import SECTIONS_DIR

MAX_SECTION_CHARS = 150   # longer titles (long risk-factor titles) are shortened in the header

log = logging.getLogger(__name__)

_SENTENCE_SPLIT = re.compile(r"(?:(?<=[.!?;])|(?<=[.!?;][\"”’)]))\s+"
                             r"(?=[\"“(•A-Z0-9])")


def short_title(title: str, limit: int = MAX_SECTION_CHARS) -> str:
    if len(title) <= limit:
        return title
    return title[:limit].rsplit(" ", 1)[0].rstrip(" ,;:") + " ..."


def _sentences(paragraph: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(paragraph) if s.strip()]


def _hard_split(word: str, max_tokens: int) -> list[str]:
    """Split one whitespace-free "word" (e.g. a 450-char underscore signature line, a dot
    leader, a long URL) into character slices of <= max_tokens tokens each."""
    if count_tokens(word) <= max_tokens or len(word) == 1:
        return [word]
    mid = len(word) // 2
    return _hard_split(word[:mid], max_tokens) + _hard_split(word[mid:], max_tokens)


def _word_windows(text: str, max_tokens: int) -> list[str]:
    """Split one over-long sentence (or table row) at word boundaries; a single word longer
    than max_tokens is itself split into character slices."""
    out, cur, cur_tok = [], [], 0
    words = [p for w in text.split() for p in _hard_split(w, max_tokens)]
    for w in words:
        t = count_tokens(w)
        if cur and cur_tok + t > max_tokens:
            out.append(" ".join(cur))
            cur, cur_tok = [], 0
        cur.append(w)
        cur_tok += t
    if cur:
        out.append(" ".join(cur))
    return out


def _tail(text: str, target: int) -> str:
    """About `target` tokens from the end of `text`, starting at a word."""
    words = text.split()
    n = max(1, int(target * 0.7))
    while n > 1 and count_tokens(" ".join(words[-n:])) > target:
        n = int(n * 0.8)
    return " ".join(words[-n:])


def split_text(paragraphs: list[str], budget: int, min_tokens: int, overlap: int) -> list[str]:
    """Pack paragraphs into pieces of <= budget tokens.

    Each piece ends at a paragraph boundary when that leaves it >= min_tokens, else at a
    sentence boundary. Consecutive pieces overlap by about `overlap` tokens (whole trailing
    sentences when they fit, else the tail words of the last sentence).
    """
    # units: (text, tokens, ends_paragraph)
    unit_max = budget - overlap - 1   # carry (<= overlap) + one unit always fits
    units: list[tuple[str, int, bool]] = []
    for p in paragraphs:
        sents = _sentences(p)
        for j, s in enumerate(sents):
            pieces = [s] if count_tokens(s) <= unit_max else _word_windows(s, unit_max // 2)
            for k, piece in enumerate(pieces):
                last = j == len(sents) - 1 and k == len(pieces) - 1
                units.append((piece, count_tokens(piece), last))
    if sum(u[1] for u in units) <= budget:
        return [_join(units)] if units else []

    chunks: list[str] = []
    i = 0
    carry: list[tuple[str, int, bool]] = []
    while i < len(units):
        cur = list(carry)
        tok = sum(u[1] for u in cur)
        n_new = 0
        while i + n_new < len(units) and tok + units[i + n_new][1] <= budget:
            tok += units[i + n_new][1]
            cur.append(units[i + n_new])
            n_new += 1
        if n_new == 0:
            # No progress (the next unit doesn't fit after the overlap carry). Units are
            # capped at unit_max so this shouldn't happen; never loop or emit carry-only
            # chunks: drop the carry, and fail loudly if even that doesn't help.
            if not carry:
                raise ValueError(f"unit of {units[i][1]} tokens exceeds budget {budget}")
            carry = []
            continue
        if i + n_new < len(units):   # not the last piece: prefer a paragraph boundary
            cut, run = None, sum(u[1] for u in carry)
            for k in range(n_new):
                run += units[i + k][1]
                if units[i + k][2] and run >= min_tokens:
                    cut = k + 1
            if cut is not None:
                cur = cur[: len(carry) + cut]
                n_new = cut
        chunks.append(_join(cur))
        i += n_new
        carry = _overlap_units(cur, overlap) if i < len(units) else []
    return chunks


def _overlap_units(cur: list[tuple[str, int, bool]], overlap: int) -> list[tuple[str, int, bool]]:
    carry: list[tuple[str, int, bool]] = []
    tok = 0
    for u in reversed(cur):
        if tok + u[1] > overlap:
            break
        carry.insert(0, u)
        tok += u[1]
    if not carry and cur:
        tail = _tail(cur[-1][0], overlap)
        carry = [(tail, count_tokens(tail), False)]
    return carry


def _join(units: list[tuple[str, int, bool]]) -> str:
    out = ""
    for k, (text, _, para_end) in enumerate(units):
        out += text
        if k < len(units) - 1:
            out += "\n\n" if para_end else " "
    return out


def split_table(table: str, budget: int) -> list[str]:
    """Split a Markdown table by rows, repeating the header row in every piece."""
    if count_tokens(table) <= budget:
        return [table]
    lines = table.split("\n")
    head = "\n".join(lines[:2])
    head_tok = count_tokens(head)
    pieces, cur, tok = [], [], head_tok
    for row in lines[2:]:
        t = count_tokens(row)
        if t > budget - head_tok:   # a single huge row: emit as plain text windows
            if cur:
                pieces.append("\n".join([head] + cur))
                cur, tok = [], head_tok
            pieces.extend(_word_windows(row, budget))
            continue
        if cur and tok + t > budget:
            pieces.append("\n".join([head] + cur))
            cur, tok = [], head_tok
        cur.append(row)
        tok += t
    if cur:
        pieces.append("\n".join([head] + cur))
    return pieces


def chunk_filing(parsed: dict) -> list[Chunk]:
    s = get_settings()
    overlap = round(s.chunk_overlap * s.chunk_max_tokens)
    chunks: list[Chunk] = []
    for item, data in parsed["items"].items():
        if item not in TEXT_ITEMS and item != FALLBACK_ITEM:
            continue   # Item 8: numbers come from XBRL
        index = 0
        for sec in data["sections"]:
            section = short_title(sec["title"])
            header = make_header(parsed["company"], "10-K", parsed["fiscal_year"], item, section)
            budget = s.chunk_max_tokens - count_tokens(header)
            # A section's prose is one stream (so table lead-ins and footnotes don't become
            # tiny chunks); each table is its own chunk.
            paras = [sec["title"]] if section != sec["title"] else []   # keep the full title
            paras += [b["text"] for b in sec["blocks"] if b["type"] == "text"]
            bodies = [(t, False) for t in split_text(paras, budget, s.chunk_min_tokens, overlap)]
            for b in sec["blocks"]:
                if b["type"] == "table":
                    bodies += [(t, True) for t in split_table(b["text"], budget)]
            for body, is_table in bodies:
                text = header + "\n\n" + body
                chunks.append(Chunk(
                    ticker=parsed["ticker"], company=parsed["company"], sector=parsed["sector"],
                    form="10-K", fiscal_year=int(parsed["fiscal_year"]),
                    period_end=str(parsed["period_end"]), item=item, section=section,
                    accession_no=parsed["accession_no"], source_url=parsed["source_url"],
                    chunk_index=index, text=text, header=header,
                    token_count=count_tokens(text), is_table=is_table,
                ))
                index += 1
    too_long = [c for c in chunks if c["token_count"] > s.chunk_max_tokens]
    if too_long:
        raise ValueError(f"{parsed['accession_no']}: {len(too_long)} chunks over "
                         f"{s.chunk_max_tokens} tokens")
    return chunks


def chunk_file(path: Path) -> int:
    parsed = json.loads(path.read_text(encoding="utf-8"))
    chunks = chunk_filing(parsed)
    return write_chunks(CHUNKS_DIR / f"{parsed['accession_no']}.jsonl", chunks)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    total = 0
    for path in sorted(SECTIONS_DIR.glob("*.json")):
        n = chunk_file(path)
        total += n
        log.info("%s -> %d chunks", path.stem, n)
    print(f"{total} chunks in {CHUNKS_DIR}")


if __name__ == "__main__":
    main()
