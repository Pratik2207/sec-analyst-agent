"""Extra Phase 2 unit tests: MD&A cross-reference resolver, fallback logging, bullet-styled
risk titles, chunk_schema helpers and chunker edge cases."""

import logging

from src.ingest import chunker
from src.ingest import parse_sections as ps
from src.ingest.chunk_schema import chunk_body, make_header, point_id

FILLER = ("The company designs and sells widgets to customers in many markets. " * 6).strip()


def _doc(item7_body: str, tail: str = "", risks: str | None = None) -> str:
    risks = risks if risks is not None else (
        f"<p><b>Our widgets may fail.</b></p><p>{FILLER}</p>"
        f"<p><b>Competition is intense.</b></p><p>{FILLER}</p>")
    return f"""<html><body>
<p>Item 1. Business</p><p>{FILLER}</p>
<p>Item 1A. Risk Factors</p>{risks}
<p>Item 7. Management's Discussion and Analysis</p>{item7_body}
<p>Item 8. Financial Statements</p><p>{FILLER}</p>
{tail}
</body></html>"""


STUB = ("<p>The information required by this Item appears on pages 40 through 90 of the "
        "Annual Report under the caption Management's Discussion and Analysis, and is "
        "incorporated herein by reference. Further detail appears in the financial review "
        "section of the annual report.</p>")
MDNA_TAIL = (f"<p>Management’s Discussion and Analysis</p>"
             f"<p><b>Executive Overview</b></p><p>Net income rose to $5.0 billion. {FILLER}</p>"
             f"<p><b>Liquidity</b></p><p>Liquidity remained strong. {FILLER}</p>"
             f"<p>Report of Independent Registered Public Accounting Firm</p>"
             f"<p>We have audited the balance sheets. {FILLER}</p>")


def _item7_text(res: dict) -> str:
    return " ".join(b["text"] for s in res["items"]["7"]["sections"] for b in s["blocks"])


# ---- MD&A cross-reference resolver ----------------------------------------------------------

def test_cross_reference_resolved_with_curly_apostrophe_and_stops_at_auditor_report():
    res = ps.parse_html(_doc(STUB, MDNA_TAIL), "X")
    assert res["fallback"] is False
    item7 = res["items"]["7"]
    assert item7["cross_reference"] is True
    assert [s["title"] for s in item7["sections"]] == ["Executive Overview", "Liquidity"]
    text = _item7_text(res)
    assert "Net income rose to $5.0 billion" in text
    assert "We have audited" not in text


def test_stub_without_page_reference_is_not_redirected():
    body = "<p>" + ("MD&A is discussed in the exhibit. " * 10) + "</p>"
    res = ps.parse_html(_doc(body, MDNA_TAIL), "X")
    assert res["items"]["7"]["cross_reference"] is False
    assert "Net income rose" not in _item7_text(res)


def test_stub_with_pages_but_no_mdna_heading_keeps_the_stub():
    res = ps.parse_html(_doc(STUB, f"<p>Some other annex. {FILLER}</p>"), "X")
    assert res["items"]["7"]["cross_reference"] is False
    assert "appears on pages 40 through 90" in _item7_text(res)


def test_long_item_7_mentioning_pages_is_not_treated_as_stub():
    body = (f"<p>See pages 10-12 for segment data. {FILLER}</p>" +
            "".join(f"<p><b>Topic {i}</b></p><p>{FILLER}</p>" for i in range(5)))
    res = ps.parse_html(_doc(body, MDNA_TAIL), "X")
    assert res["items"]["7"]["cross_reference"] is False
    assert "Topic 0" in [s["title"] for s in res["items"]["7"]["sections"]]


# ---- fallback logging (X-4) -------------------------------------------------------------------

def test_fallback_logged_as_warning_by_parser_logger(caplog):
    html = f"<html><body><p>Annual report</p><p>{FILLER}</p></body></html>"
    with caplog.at_level(logging.WARNING, logger="src.ingest.parse_sections"):
        res = ps.parse_html(html, "0000000001-25-000009")
    assert res["fallback"] is True and list(res["items"]) == ["full"]
    recs = [r for r in caplog.records if r.name == "src.ingest.parse_sections"]
    assert len(recs) == 1 and recs[0].levelno == logging.WARNING
    msg = recs[0].getMessage()
    assert "0000000001-25-000009" in msg and "1, 1A, 7" in msg


def test_no_warning_when_items_found(caplog):
    with caplog.at_level(logging.WARNING, logger="src.ingest.parse_sections"):
        res = ps.parse_html(_doc(f"<p>{FILLER}</p>"), "X")
    assert res["fallback"] is False
    assert not [r for r in caplog.records if r.name == "src.ingest.parse_sections"]


def test_fallback_document_is_chunked_with_full_item(monkeypatch):
    html = f"<html><body><p><b>Overview</b></p><p>{FILLER}</p></body></html>"
    parsed = {"ticker": "ODD", "company": "Oddco", "sector": "x", "fiscal_year": 2024,
              "period_end": "2024-12-31", "accession_no": "A-1", "source_url": "u",
              **ps.parse_html(html, "A-1")}
    chunks = chunker.chunk_filing(parsed)
    assert chunks and {c["item"] for c in chunks} == {"full"}
    assert chunks[0]["header"] == "[Oddco | 10-K | FY2024 | Full document | Overview]"


# ---- one section per risk, with bullet-styled bold titles (FR-4) ------------------------------

def test_bold_bullet_risk_titles_each_start_a_section():
    """Some filers (e.g. LLY FY2023/24) write each risk title as a bold bullet paragraph."""
    risks = (f"<p><b>Risks Related to Our Business</b></p>"
             f"<p><b>•We may fail to develop new products.</b></p><p>{FILLER}</p>"
             f"<p><b>•We depend on patent protection.</b></p><p>{FILLER}</p>"
             f"<p><b>•Pricing pressure may reduce revenue.</b></p><p>{FILLER}</p>")
    res = ps.parse_html(_doc(f"<p>{FILLER}</p>", risks=risks), "X")
    titles = [s["title"] for s in res["items"]["1A"]["sections"]]
    assert len([t for t in titles if "We " in t or "Pricing" in t]) == 3, titles


def test_plain_bullets_in_body_are_not_headings():
    risks = (f"<p><b>Our widgets may fail.</b></p><p>{FILLER}</p>"
             f"<p>• first plain bullet point</p><p>• second plain bullet point</p>")
    res = ps.parse_html(_doc(f"<p>{FILLER}</p>", risks=risks), "X")
    assert [s["title"] for s in res["items"]["1A"]["sections"]] == ["Our widgets may fail."]


# ---- chunk_schema helpers ---------------------------------------------------------------------

def test_point_id_deterministic_and_distinct():
    a = point_id("0001-25-1", "7", 3)
    assert a == point_id("0001-25-1", "7", 3)
    assert len({a, point_id("0001-25-1", "7", 4), point_id("0001-25-1", "1A", 3),
                point_id("0001-25-2", "7", 3)}) == 4


def test_make_header_variants_and_chunk_body_roundtrip():
    h = make_header("NVIDIA", "10-K", 2025, "7", "Gross Margin")
    assert h == "[NVIDIA | 10-K | FY2025 | Item 7 MD&A | Gross Margin]"
    assert make_header("X", "10-K", 2024, "1A", "") == "[X | 10-K | FY2024 | Item 1A Risk Factors]"
    assert make_header("X", "10-K", 2024, "full", "") == "[X | 10-K | FY2024 | Full document]"
    chunk = {"header": h, "text": h + "\n\nbody text"}
    assert chunk_body(chunk) == "body text"


def test_short_title_cuts_at_word_and_marks():
    assert chunker.short_title("short") == "short"
    long = "word " * 60
    out = chunker.short_title(long)
    assert out.endswith(" ...") and len(out) <= chunker.MAX_SECTION_CHARS + 4


# ---- chunker edge cases -----------------------------------------------------------------------

def test_split_text_empty_and_small():
    assert chunker.split_text([], 400, 300, 72) == []
    assert chunker.split_text(["One sentence."], 400, 300, 72) == ["One sentence."]


def test_split_text_pieces_within_budget_and_cover_all_text():
    paras = [" ".join(f"Sentence {j} of paragraph {i} discusses margins and costs."
                      for j in range(12)) for i in range(15)]
    from src.ingest.chunk_schema import count_tokens

    pieces = chunker.split_text(paras, 200, 120, 30)
    assert len(pieces) > 1
    assert all(count_tokens(p) <= 200 for p in pieces)
    joined = " ".join(pieces)
    for i in range(15):
        assert f"Sentence 11 of paragraph {i} " in joined


def test_split_table_repeats_header_row():
    head = "| Segment | 2024 | 2023 |\n| --- | --- | --- |"
    rows = "\n".join(f"| Segment {i} with a long descriptive name | ${i},000 | ${i},500 |"
                     for i in range(60))
    pieces = chunker.split_table(head + "\n" + rows, 150)
    assert len(pieces) > 1
    assert all(p.startswith(head) for p in pieces)
    assert sum(p.count("\n") - 1 for p in pieces) == 60


def test_item_8_skipped():
    parsed = {"ticker": "T", "company": "T", "sector": "x", "fiscal_year": 2024,
              "period_end": "2024-12-31", "accession_no": "A", "source_url": "u",
              "items": {"8": {"sections": [{"title": "", "blocks": [
                  {"type": "text", "text": FILLER}]}]}}}
    assert chunker.chunk_filing(parsed) == []
