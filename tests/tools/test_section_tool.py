"""get_section tool: truncation, validation, and the real Phase 2 sections files (read-only)."""

import json
from pathlib import Path

import pytest

from src.ingest.chunk_schema import count_tokens
from src.tools import section_tool

REAL_DATA = Path(__file__).resolve().parents[2] / "data"
if not (REAL_DATA / "processed" / "sections").exists():  # running inside a git worktree
    REAL_DATA = Path("D:/Code/SEC Anaylst/data")
REAL_MANIFEST = REAL_DATA / "raw" / "filings" / "manifest.jsonl"
REAL_SECTIONS = REAL_DATA / "processed" / "sections"

needs_real = pytest.mark.skipif(not REAL_SECTIONS.exists(), reason="no parsed sections")


@pytest.fixture
def real_paths(monkeypatch):
    monkeypatch.setattr(section_tool, "MANIFEST_PATH", REAL_MANIFEST)
    monkeypatch.setattr(section_tool, "SECTIONS_DIR", REAL_SECTIONS)


ACCN = "0000000000-25-000001"


@pytest.fixture
def fake_paths(tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.jsonl"
    rec = {"ticker": "NVDA", "cik": "0001045810", "company": "NVIDIA", "fiscal_year": 2025,
           "accession_no": ACCN, "source_url": "https://www.sec.gov/Archives/x/nvda.htm"}
    fb = {**rec, "ticker": "INTC", "accession_no": "0000000000-25-000002"}
    manifest.write_text(json.dumps(rec) + "\n" + json.dumps(fb) + "\n", encoding="utf-8")
    sections = tmp_path / "sections"
    sections.mkdir()
    para = "Revenue grew strongly. Gross margin expanded. " * 20
    table = {"type": "table", "text": "| a | b |\n| --- | --- |"}
    items = {"7": {"heading": "Item 7.", "cross_reference": False, "sections": [
        {"title": "", "blocks": [{"type": "text", "text": "Intro paragraph."}]},
        {"title": "Gross Margin", "blocks": [{"type": "text", "text": para}, table]},
    ]}, "1": {"heading": "Item 1.", "cross_reference": False, "sections": [
        {"title": "", "blocks": [{"type": "text", "text": "word " * 400}]}]}}
    (sections / f"{ACCN}.json").write_text(
        json.dumps({**rec, "fallback": False, "items": items}), encoding="utf-8")
    (sections / "0000000000-25-000002.json").write_text(
        json.dumps({**fb, "fallback": True, "items": {"full": {"sections": []}}}),
        encoding="utf-8")
    monkeypatch.setattr(section_tool, "MANIFEST_PATH", manifest)
    monkeypatch.setattr(section_tool, "SECTIONS_DIR", sections)


def test_joins_titles_and_blocks(fake_paths):
    res = section_tool.call("NVDA", 2025, "7", max_tokens=6000)
    assert res.ok
    d = res.data[0]
    assert d["truncated"] is False
    assert d["text"].startswith("Intro paragraph.\n\nGross Margin\n\nRevenue grew")
    assert d["text"].endswith("| a | b |\n| --- | --- |")
    assert d["source_id"] == f"section:{ACCN}:7"


def test_truncates_at_paragraph_boundary(fake_paths):
    res = section_tool.call("NVDA", 2025, "7", max_tokens=100)
    d = res.data[0]
    assert d["truncated"] is True
    assert count_tokens(d["text"]) <= 100
    assert d["text"] == "Intro paragraph.\n\nGross Margin"  # whole paragraphs that fit


def test_truncate_long_first_paragraph():
    text, cut = section_tool.truncate("One two three. " * 100, 20)
    assert cut and text.endswith(".") and count_tokens(text) <= 20
    text, cut = section_tool.truncate("word " * 300, 50)
    assert cut and 0 < count_tokens(text) <= 50


def test_citation_from_section_source(fake_paths):
    res = section_tool.call("nvda", "2025", "7")
    src = res.source(res.data[0]["source_id"])
    c = src.citation()
    assert (c.ticker, c.fiscal_year, c.form, c.section) == ("NVDA", 2025, "10-K", "Item 7 MD&A")
    assert c.accession_no == ACCN and c.url == "https://www.sec.gov/Archives/x/nvda.htm"


@pytest.mark.parametrize("args,needle", [
    (("ZZZZ", 2025, "7"), "valid"),
    (("NVDA", 2030, "7"), "2025"),
    (("NVDA", 2025, "8"), "1A"),
    (("NVDA", 2025, "full"), "7A"),
    (("NVDA", True, "7"), "integer"),
    (("NVDA", "soon", "7"), "integer"),
    (("AMD", 2025, "7"), "no 10-K loaded"),
])
def test_invalid_arguments(fake_paths, args, needle):
    res = section_tool.call(*args)
    assert not res.ok and needle in res.error


def test_missing_item_suggests_item_7(fake_paths):
    res = section_tool.call("NVDA", 2025, "7A")
    assert not res.ok and "item 7" in res.error


def test_fallback_filing(fake_paths):
    res = section_tool.call("INTC", 2025, "7")
    assert not res.ok and "search_filings" in res.error


# ---- the real Phase 2 parser output (read-only) ---------------------------------------------

@needs_real
def test_real_nvda_item7(real_paths):
    res = section_tool.call("NVDA", 2025, "7", max_tokens=1500)
    assert res.ok, res.error
    d = res.data[0]
    assert d["text"] and d["truncated"] is True
    assert count_tokens(d["text"]) <= 1500
    src = res.source(d["source_id"])
    assert src.url.startswith("https://www.sec.gov/") and src.citation() is not None


@needs_real
def test_real_intc_is_fallback(real_paths):
    res = section_tool.call("INTC", 2024, "7")
    assert not res.ok and "no Item structure" in res.error and "search_filings" in res.error


@needs_real
def test_real_jpm_7a_cross_referenced(real_paths):
    res = section_tool.call("JPM", 2024, "7A")
    assert not res.ok and "item 7" in res.error
