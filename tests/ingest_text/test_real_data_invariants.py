"""Phase 2 invariants over the real pilot data under data/ (read-only).

Integration: needs the downloaded filings and the processed sections/chunks, and the
docker postgres for the manifest-vs-financial_facts check.
"""

import json
import re
from collections import Counter, defaultdict

import pytest

from config.settings import ROOT, get_settings
from src.ingest.chunk_schema import (
    CHUNKS_DIR,
    FALLBACK_ITEM,
    TEXT_ITEMS,
    Chunk,
    chunk_body,
    count_tokens,
    make_header,
    point_id,
    read_chunks,
)
from src.ingest.download_filings import MANIFEST
from src.ingest.parse_sections import REQUIRED_ITEMS, SECTIONS_DIR

pytestmark = pytest.mark.integration

if not MANIFEST.exists() or not any(CHUNKS_DIR.glob("*.jsonl")):
    pytest.skip("pilot data not present", allow_module_level=True)

RECORDS = [json.loads(line) for line in MANIFEST.read_text(encoding="utf-8").splitlines()
           if line.strip()]
CHUNK_FILES = sorted(CHUNKS_DIR.glob("*.jsonl"))
ALL_CHUNKS = [c for p in CHUNK_FILES for c in read_chunks(p)]
HEADER_RE = re.compile(r"^\[[^|\]]+ \| 10-K \| FY\d{4} \| "
                       r"(Item (1|1A|7|7A) [^|\]]+|Full document)( \| [^\]]+)?\]$")


# ---- manifest / downloads (FR-1, AC1) ---------------------------------------------------------

def test_manifest_has_about_30_unique_filings_on_disk():
    assert 28 <= len(RECORDS) <= 30
    assert len({r["accession_no"] for r in RECORDS}) == len(RECORDS)
    assert len({(r["ticker"], r["fiscal_year"]) for r in RECORDS}) == len(RECORDS)
    for r in RECORDS:
        path = ROOT / r["path"]
        assert path.is_file() and path.stat().st_size > 10_000, r["path"]
        assert r["source_url"].startswith("https://www.sec.gov/Archives/edgar/data/")


def test_manifest_covers_pilot_companies_fy2023_to_2025():
    from config.settings import load_companies

    pilot = {c["ticker"] for c in load_companies(pilot_only=True)}
    assert {r["ticker"] for r in RECORDS} == pilot
    per_ticker = Counter(r["ticker"] for r in RECORDS)
    assert all(n == 3 for n in per_ticker.values()), per_ticker
    assert {r["fiscal_year"] for r in RECORDS} <= {2023, 2024, 2025}


def test_manifest_matches_financial_facts_accessions():
    from src.ingest.download_filings import load_refs

    try:
        refs = load_refs()
    except Exception as e:   # postgres not reachable
        pytest.skip(f"financial_facts not readable: {e}")
    db = {(r["ticker"], r["fiscal_year"], r["accession_no"], str(r["period_end"]))
          for r in refs}
    man = {(r["ticker"], r["fiscal_year"], r["accession_no"], str(r["period_end"]))
           for r in RECORDS}
    assert man == db


# ---- sections (FR-4, X-4, AC2) ---------------------------------------------------------------

def test_every_filing_has_items_1_1a_7_or_logged_fallback():
    for r in RECORDS:
        parsed = json.loads((SECTIONS_DIR / f"{r['accession_no']}.json")
                            .read_text(encoding="utf-8"))
        if parsed["fallback"]:
            assert list(parsed["items"]) == [FALLBACK_ITEM], r["accession_no"]
        else:
            assert set(REQUIRED_ITEMS) <= set(parsed["items"]), r["accession_no"]
            for k in REQUIRED_ITEMS:
                assert parsed["items"][k]["sections"], (r["accession_no"], k)


def test_fallback_is_rare_and_limited_to_known_filings():
    fallback = []
    for r in RECORDS:
        parsed = json.loads((SECTIONS_DIR / f"{r['accession_no']}.json")
                            .read_text(encoding="utf-8"))
        if parsed["fallback"]:
            fallback.append(r["ticker"])
    assert set(fallback) <= {"INTC"}, fallback


def test_risk_factors_are_split_into_many_sections():
    """One section per risk: every non-fallback 1A has many titled sections (each pilot
    10-K lists 16+ risks)."""
    few = []
    for r in RECORDS:
        parsed = json.loads((SECTIONS_DIR / f"{r['accession_no']}.json")
                            .read_text(encoding="utf-8"))
        if parsed["fallback"]:
            continue
        titled = [s for s in parsed["items"]["1A"]["sections"] if s["title"]]
        if len(titled) < 15:
            few.append((r["ticker"], r["fiscal_year"], len(titled)))
    assert few == []


# ---- chunks (FR-5, AC3, AC4) -------------------------------------------------------------------

def test_one_chunk_file_per_manifest_filing():
    assert {p.stem for p in CHUNK_FILES} == {r["accession_no"] for r in RECORDS}


def test_every_chunk_has_exactly_the_chunk_keys():
    keys = set(Chunk.__annotations__)
    for c in ALL_CHUNKS:
        assert set(c) == keys, c.get("accession_no")


def test_chunk_payload_matches_manifest():
    by_acc = {r["accession_no"]: r for r in RECORDS}
    for c in ALL_CHUNKS:
        r = by_acc[c["accession_no"]]
        assert c["form"] == "10-K"
        for k in ("ticker", "company", "sector", "fiscal_year", "period_end", "source_url"):
            assert c[k] == r[k], (k, c["accession_no"])
        assert isinstance(c["fiscal_year"], int) and isinstance(c["chunk_index"], int)
        assert c["item"] in TEXT_ITEMS or c["item"] == FALLBACK_ITEM


def test_every_chunk_within_token_limit_and_count_is_correct():
    limit = get_settings().chunk_max_tokens
    assert limit <= 800
    over = [(c["accession_no"], c["item"], c["chunk_index"]) for c in ALL_CHUNKS
            if c["token_count"] > limit]
    assert over == []
    # token_count is the real count of `text` (spot-check a sample)
    for c in ALL_CHUNKS[::97]:
        assert c["token_count"] == count_tokens(c["text"])


def test_header_format_and_text_starts_with_header():
    for c in ALL_CHUNKS:
        assert HEADER_RE.match(c["header"]), c["header"]
        assert c["header"] == make_header(c["company"], c["form"], c["fiscal_year"],
                                          c["item"], c["section"])
        assert c["text"].startswith(c["header"] + "\n\n")


def test_no_empty_bodies():
    empty = [(c["accession_no"], c["chunk_index"]) for c in ALL_CHUNKS
             if not chunk_body(c).strip()]
    assert empty == []


def test_chunk_index_unique_and_contiguous_per_filing_item():
    groups = defaultdict(list)
    for c in ALL_CHUNKS:
        groups[(c["accession_no"], c["item"])].append(c["chunk_index"])
    for key, idx in groups.items():
        assert sorted(idx) == list(range(len(idx))), key


def test_point_ids_unique_across_corpus():
    ids = [point_id(c["accession_no"], c["item"], c["chunk_index"]) for c in ALL_CHUNKS]
    assert len(set(ids)) == len(ids)


def test_mdna_tables_present_and_markdown():
    """AC3: MD&A tables become Markdown chunks. (Outside MD&A, a single table row over the
    budget is emitted as plain-text windows by design; see chunker.split_table.)"""
    tables = [c for c in ALL_CHUNKS if c["is_table"] and c["item"] == "7"]
    assert len(tables) >= 30
    for c in tables:
        lines = chunk_body(c).split("\n")
        assert lines[0].startswith("|"), (c["accession_no"], c["chunk_index"])
        assert re.fullmatch(r"\|( --- \|)+", lines[1]), (c["accession_no"], c["chunk_index"])


def test_split_sections_overlap_about_15_percent():
    """Consecutive text pieces of one split section share a carried-over prefix."""
    s = get_settings()
    target = s.chunk_overlap * s.chunk_max_tokens   # 72 tokens
    groups = defaultdict(list)
    for c in ALL_CHUNKS:
        if not c["is_table"]:
            groups[(c["accession_no"], c["item"], c["section"])].append(c)
    measured, missing = [], []
    for chunks in groups.values():
        chunks.sort(key=lambda c: c["chunk_index"])
        for a, b in zip(chunks, chunks[1:], strict=False):
            if b["chunk_index"] != a["chunk_index"] + 1:
                continue
            body_a, body_b = chunk_body(a), chunk_body(b)
            # longest prefix of b that is a suffix-region substring of a
            words = body_b.split()
            n = 0
            while n < len(words) and " ".join(words[: n + 1]) in body_a:
                n += 1
            if n == 0:
                missing.append((a["accession_no"], a["item"], a["chunk_index"]))
            else:
                measured.append(count_tokens(" ".join(words[:n])))
    assert measured, "no split sections found"
    assert len(missing) <= 0.02 * (len(measured) + len(missing)), missing[:5]
    median = sorted(measured)[len(measured) // 2]
    assert 0.5 * target <= median <= 1.5 * target, median
