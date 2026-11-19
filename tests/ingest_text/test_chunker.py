import json
from collections import Counter
from pathlib import Path

from config.settings import get_settings
from src.ingest import chunker
from src.ingest.chunk_schema import Chunk, chunk_body, count_tokens, read_chunks
from src.ingest.parse_sections import parse_html

FIX = Path(__file__).parent / "fixtures"
META = {"ticker": "ACME", "cik": "0000012345", "company": "Acme", "sector": "industrials",
        "fiscal_year": 2024, "period_end": "2024-12-31", "accession_no": "0000012345-25-000010",
        "source_url": "https://www.sec.gov/Archives/edgar/data/12345/000001234525000010/a.htm",
        "path": "x"}
MAX = get_settings().chunk_max_tokens
MIN = get_settings().chunk_min_tokens
OVERLAP = round(get_settings().chunk_overlap * MAX)


def sentence(i: int) -> str:
    return (f"Sentence number {i} explains how the widget business performed during the "
            f"fiscal year and why revenue changed compared with the prior period.")


def long_section(n_paras=12, sents_per_para=5, title="Results of Operations") -> dict:
    paras = [" ".join(sentence(p * 100 + s) for s in range(sents_per_para))
             for p in range(n_paras)]
    return {"title": title, "blocks": [{"type": "text", "text": p} for p in paras]}


def parsed(items: dict) -> dict:
    return {**META, "fallback": False,
            "items": {k: {"heading": f"Item {k}", "cross_reference": False, "sections": v}
                      for k, v in items.items()}}


def test_header_payload_and_text_format():
    sec = {"title": "Gross Margin", "blocks": [{"type": "text", "text": "Margin rose."}]}
    (c,) = chunker.chunk_filing(parsed({"7": [sec]}))
    assert set(c) == set(Chunk.__annotations__)
    assert c["header"] == "[Acme | 10-K | FY2024 | Item 7 MD&A | Gross Margin]"
    assert c["text"] == c["header"] + "\n\nMargin rose."
    assert chunk_body(c) == "Margin rose."
    assert c["token_count"] == count_tokens(c["text"])
    assert (c["ticker"], c["sector"], c["form"], c["fiscal_year"], c["period_end"]) == (
        "ACME", "industrials", "10-K", 2024, "2024-12-31")
    assert (c["item"], c["section"], c["chunk_index"], c["is_table"]) == ("7", "Gross Margin",
                                                                          0, False)
    assert c["accession_no"] == META["accession_no"] and c["source_url"] == META["source_url"]


def test_intro_section_header_has_no_section_part():
    sec = {"title": "", "blocks": [{"type": "text", "text": "Intro text."}]}
    (c,) = chunker.chunk_filing(parsed({"1A": [sec]}))
    assert c["header"] == "[Acme | 10-K | FY2024 | Item 1A Risk Factors]"
    assert c["section"] == ""


def test_long_section_split_within_limits_with_overlap():
    chunks = chunker.chunk_filing(parsed({"7": [long_section()]}))
    assert len(chunks) > 3
    assert all(c["token_count"] <= MAX for c in chunks)
    assert all(c["token_count"] >= MIN for c in chunks[:-1])
    assert all(c["header"] == "[Acme | 10-K | FY2024 | Item 7 MD&A | Results of Operations]"
               for c in chunks)
    for a, b in zip(chunks, chunks[1:], strict=False):
        x, y = chunk_body(a), chunk_body(b)
        shared = next(n for n in range(min(len(x), len(y)), 0, -1) if x.endswith(y[:n]))
        overlap_tokens = count_tokens(y[:shared])
        assert 0.05 * MAX <= overlap_tokens <= OVERLAP   # about 15%, never more
    # all text is kept, in order
    body = " ".join(chunk_body(c) for c in chunks)
    for i in (0, 504, 1102, 1104):
        assert sentence(i) in body


def test_splits_prefer_paragraph_boundaries():
    chunks = chunker.chunk_filing(parsed({"7": [long_section(n_paras=12, sents_per_para=5)]}))
    for c in chunks[:-1]:
        # each piece ends with the last sentence of a paragraph (sentence numbers x04)
        last_no = int(chunk_body(c).rsplit("Sentence number ", 1)[1].split()[0])
        assert last_no % 100 == 4
        assert chunk_body(c).endswith(sentence(last_no))


def test_unpunctuated_text_is_split_by_words():
    blob = " ".join(f"word{i}" for i in range(3000))
    sec = {"title": "Blob", "blocks": [{"type": "text", "text": blob}]}
    chunks = chunker.chunk_filing(parsed({"1": [sec]}))
    assert len(chunks) > 1
    assert all(c["token_count"] <= MAX for c in chunks)
    assert "word2999" in chunk_body(chunks[-1])


def test_tables_are_own_chunks_and_large_tables_split_by_rows():
    small = "| Segment | 2024 |\n| --- | --- |\n| Industrial | $900 |"
    rows = "\n".join(f"| Line item number {i} with a long description | ${i},000 | {i}% |"
                     for i in range(60))
    big = "| Line | 2024 | Change |\n| --- | --- | --- |\n" + rows
    sec = {"title": "Revenue", "blocks": [{"type": "text", "text": "Revenue rose."},
                                          {"type": "table", "text": small},
                                          {"type": "text", "text": "See the table."},
                                          {"type": "table", "text": big}]}
    chunks = chunker.chunk_filing(parsed({"7": [sec]}))
    text_chunks = [c for c in chunks if not c["is_table"]]
    tables = [c for c in chunks if c["is_table"]]
    assert [chunk_body(c) for c in text_chunks] == ["Revenue rose.\n\nSee the table."]
    assert chunk_body(tables[0]) == small
    assert len(tables) > 2
    for t in tables[1:]:
        assert chunk_body(t).startswith("| Line | 2024 | Change |\n| --- | --- | --- |\n")
        assert t["token_count"] <= MAX
    all_rows = "\n".join(chunk_body(t) for t in tables[1:])
    assert all(f"| Line item number {i} " in all_rows for i in range(60))


def test_chunk_index_unique_and_contiguous_per_item():
    p = parsed({"1": [long_section(title="A"), long_section(title="B")],
                "1A": [long_section(title="Risk one."), long_section(title="Risk two.")],
                "7": [long_section()]})
    chunks = chunker.chunk_filing(p)
    for item in ("1", "1A", "7"):
        idx = [c["chunk_index"] for c in chunks if c["item"] == item]
        assert idx == list(range(len(idx)))
    keys = Counter((c["accession_no"], c["item"], c["chunk_index"]) for c in chunks)
    assert max(keys.values()) == 1


def test_item_8_is_not_chunked_and_fallback_is():
    p = parsed({"7": [long_section(n_paras=1)], "8": [long_section(n_paras=1)]})
    assert {c["item"] for c in chunker.chunk_filing(p)} == {"7"}
    full = {**META, "fallback": True, "items": {"full": {
        "heading": "", "cross_reference": False, "sections": [long_section(title="")]}}}
    chunks = chunker.chunk_filing(full)
    assert {c["item"] for c in chunks} == {"full"}
    assert chunks[0]["header"] == "[Acme | 10-K | FY2024 | Full document]"
    assert all(c["token_count"] <= MAX for c in chunks)


def test_long_risk_title_shortened_in_header_but_kept_in_body():
    title = ("Our business could be harmed by a long list of things " * 8).strip() + "."
    sec = {"title": title, "blocks": [{"type": "text", "text": "Details of the risk."}]}
    (c,) = chunker.chunk_filing(parsed({"1A": [sec]}))
    assert len(c["section"]) <= chunker.MAX_SECTION_CHARS + 4
    assert c["section"].endswith("...")
    assert chunk_body(c) == title + "\n\nDetails of the risk."


def test_end_to_end_on_fixture(tmp_path, monkeypatch):
    p = {**META, **parse_html((FIX / "synthetic_10k.htm").read_bytes(), "x")}
    sections_dir = tmp_path / "sections"
    sections_dir.mkdir()
    (sections_dir / f"{META['accession_no']}.json").write_text(json.dumps(p), encoding="utf-8")
    monkeypatch.setattr(chunker, "SECTIONS_DIR", sections_dir)
    monkeypatch.setattr(chunker, "CHUNKS_DIR", tmp_path / "chunks")
    chunker.main()
    chunks = list(read_chunks(tmp_path / "chunks" / f"{META['accession_no']}.jsonl"))
    assert {c["item"] for c in chunks} == {"1", "1A", "7", "7A"}
    risks = [c for c in chunks if c["item"] == "1A"]
    assert [c["section"] for c in risks] == [
        "", "Demand for widgets is cyclical and a downturn could reduce our revenue.",
        "We depend on a small number of suppliers for steel.",
        "New environmental rules could increase our costs."]
    (table,) = [c for c in chunks if c["is_table"]]
    assert table["section"] == "Revenue" and "| Industrial | $900 |" in table["text"]
    for c in chunks:
        assert c["text"].startswith(c["header"] + "\n\n")
        assert c["token_count"] == count_tokens(c["text"]) <= MAX


def test_real_nvda_excerpt_chunks_within_limits():
    p = {**META, **parse_html((FIX / "nvda_excerpt.htm").read_bytes(), "x")}
    chunks = chunker.chunk_filing(p)
    assert chunks and all(c["token_count"] <= MAX for c in chunks)
