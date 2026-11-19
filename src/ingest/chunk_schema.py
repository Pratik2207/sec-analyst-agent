"""Phase 2 interface contract: the chunk record shared by the chunker (track-a) and the
indexer/search (track-b). Owned by the main session; tracks must not change it.

A chunk file is `data/processed/chunks/<accession_no>.jsonl`, one JSON object per line,
with exactly the keys of `Chunk`.
"""

import json
import uuid
from collections.abc import Iterable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

from config.settings import DATA_DIR, get_settings

CHUNKS_DIR = DATA_DIR / "processed" / "chunks"

# Items kept as text (PRD 7.1). "full" = whole-document fallback when Items can't be found.
TEXT_ITEMS = ("1", "1A", "7", "7A")
FALLBACK_ITEM = "full"
ITEM_NAMES = {"1": "Business", "1A": "Risk Factors", "7": "MD&A", "7A": "Market Risk",
              "8": "Financial Statements", FALLBACK_ITEM: "Full document"}

POINT_NAMESPACE = uuid.UUID("6f1c1d2e-7a54-4b8e-9a51-5ec0a5a11c01")


class Chunk(TypedDict):
    # PRD 7.2 payload
    ticker: str
    company: str
    sector: str
    form: str            # "10-K"
    fiscal_year: int
    period_end: str      # ISO date
    item: str            # one of TEXT_ITEMS or FALLBACK_ITEM
    section: str         # subheading, risk title, or "" for an item's intro text
    accession_no: str
    source_url: str      # the 10-K primary document on sec.gov
    chunk_index: int     # 0-based, unique within (accession_no, item)
    text: str            # header + "\n\n" + body  (what gets embedded)
    # additions
    header: str          # "[NVIDIA | 10-K | FY2025 | Item 7 MD&A | Gross Margin]"
    token_count: int     # count_tokens(text)
    is_table: bool       # body is a Markdown table


def make_header(company: str, form: str, fiscal_year: int, item: str, section: str) -> str:
    item_label = "Full document" if item == FALLBACK_ITEM else f"Item {item} {ITEM_NAMES[item]}"
    parts = [company, form, f"FY{fiscal_year}", item_label] + ([section] if section else [])
    return "[" + " | ".join(parts) + "]"


def chunk_body(chunk: Chunk) -> str:
    """The text without its context header (needed for the Phase 5 'no headers' ablation)."""
    return chunk["text"][len(chunk["header"]) + 2:]


def point_id(accession_no: str, item: str, chunk_index: int) -> str:
    """Deterministic Qdrant point ID, so re-indexing overwrites instead of duplicating."""
    return str(uuid.uuid5(POINT_NAMESPACE, f"{accession_no}|{item}|{chunk_index}"))


@lru_cache
def _tokenizer():
    from tokenizers import Tokenizer

    return Tokenizer.from_pretrained(get_settings().embed_model)


def count_tokens(text: str) -> int:
    """Tokens as the embedding model sees them (bge WordPiece), excluding [CLS]/[SEP]."""
    return len(_tokenizer().encode(text, add_special_tokens=False).ids)


def write_chunks(path: Path, chunks: Iterable[Chunk]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_chunks(path: Path) -> Iterator[Chunk]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)
