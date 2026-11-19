import json
import logging
from pathlib import Path

import pytest

from config.settings import DATA_DIR
from src.ingest import parse_sections as ps

FIX = Path(__file__).parent / "fixtures"


def parse(name: str, accession_no: str = "TEST-ACCN") -> dict:
    return ps.parse_html((FIX / name).read_bytes(), accession_no)


def all_text(item: dict) -> str:
    return "\n".join(b["text"] for s in item["sections"] for b in s["blocks"])


def titles(item: dict) -> list[str]:
    return [s["title"] for s in item["sections"]]


# --- synthetic 10-K -------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic():
    return parse("synthetic_10k.htm")


def test_items_found_and_toc_skipped(synthetic):
    assert synthetic["fallback"] is False
    assert list(synthetic["items"]) == ["1", "1A", "7", "7A", "8"]
    # the real headings were chosen, not the table-of-contents rows
    assert synthetic["items"]["1"]["heading"] == "ITEM 1. BUSINESS"
    assert synthetic["items"]["1A"]["heading"] == "Item 1A. Risk Factors"
    assert "Acme Corp designs and sells widgets" in all_text(synthetic["items"]["1"])


def test_items_do_not_bleed_into_each_other(synthetic):
    items = synthetic["items"]
    assert "Investing in our securities" not in all_text(items["1"])
    assert "None." not in all_text(items["1A"])      # Item 1B body is not part of 1A
    assert "Interest Rate Risk" not in titles(items["7"])
    assert "None." not in all_text(items["8"])       # Item 9 ends Item 8


def test_subheading_split(synthetic):
    assert titles(synthetic["items"]["1"]) == ["Our Company", "Competition", "Human Capital"]
    assert titles(synthetic["items"]["7"]) == ["", "Revenue", "Gross Margin",
                                              "Quarterly Shipments"]
    assert titles(synthetic["items"]["7A"]) == ["Interest Rate Risk", "Foreign Exchange Risk"]


def test_one_section_per_risk_factor(synthetic):
    # category headings ("Risks Related to ...") are followed directly by a risk title,
    # so each section is one risk; the intro text is the untitled section
    assert titles(synthetic["items"]["1A"]) == [
        "",
        "Demand for widgets is cyclical and a downturn could reduce our revenue.",
        "We depend on a small number of suppliers for steel.",
        "New environmental rules could increase our costs.",
    ]
    risk = synthetic["items"]["1A"]["sections"][2]
    assert [b["text"] for b in risk["blocks"]] == [
        "Three suppliers provide most of our steel. A disruption at any of them could "
        "delay our shipments."]


def test_italic_paragraph_is_not_a_heading(synthetic):
    comp = synthetic["items"]["1"]["sections"][1]
    assert any(b["text"].startswith("Our competitive advantages") for b in comp["blocks"])


def test_small_table_is_markdown_with_merged_cells(synthetic):
    revenue = synthetic["items"]["7"]["sections"][1]
    (table,) = [b["text"] for b in revenue["blocks"] if b["type"] == "table"]
    lines = table.split("\n")
    assert lines[1].startswith("| --- |")
    assert "| Industrial | $900 | $780 | 15% |" in lines
    assert "| Total | $1,200 | $1,071 | 12% |" in lines


def test_large_table_dropped_and_bullet_table_kept_as_text(synthetic):
    shipments = synthetic["items"]["7"]["sections"][3]
    assert [b["type"] for b in shipments["blocks"]] == ["text"]   # 33-row table dropped
    comp = all_text(synthetic["items"]["1"])
    assert "\u2022 Catalog: we offer more than 5,000 widget models." in comp


def test_page_furniture_removed_and_page_break_joined(synthetic):
    text = "\n".join(all_text(it) for it in synthetic["items"].values())
    assert "Table of Contents" not in text
    assert "Acme Corp 2024 Form 10-K" not in text
    assert "HIDDEN XBRL" not in text
    assert ("we sell them through direct sales and a network of distributors in more than "
            "forty countries.") in text


# --- other fixtures --------------------------------------------------------------------

def test_fallback_on_malformed_document(caplog):
    with caplog.at_level(logging.WARNING):
        res = parse("malformed_10k.htm", "0000000000-24-000001")
    assert res["fallback"] is True
    assert list(res["items"]) == ["full"]
    text = all_text(res["items"]["full"])
    assert "Oddco sells three gadget lines" in text
    assert "Gadget demand is seasonal" in text
    assert "0000000000-24-000001" in caplog.text and "not found" in caplog.text


def test_fallback_when_one_required_item_missing(caplog):
    html = (FIX / "synthetic_10k.htm").read_text(encoding="utf-8")
    html = html.replace("Item&#160;1A. Risk Factors", "Risk Factors").replace(
        "Item 1A.", "Risks.")
    res = ps.parse_html(html, "X-1")
    assert res["fallback"] is True and list(res["items"]) == ["full"]
    assert "1A" in caplog.text


def test_mdna_cross_reference_is_resolved():
    res = parse("annual_report_10k.htm")
    assert res["fallback"] is False
    item7 = res["items"]["7"]
    assert item7["cross_reference"] is True
    assert titles(item7) == ["", "EXECUTIVE OVERVIEW", "MARKET RISK MANAGEMENT"]
    text = all_text(item7)
    assert "net income of $9.1 billion" in text
    assert "internal control" not in text           # stops at management's report
    assert "Risk Factors" not in titles(res["items"]["1A"])
    assert len(res["items"]["1A"]["sections"]) == 2


def test_real_excerpt_nvda():
    """Trimmed excerpt of NVIDIA's FY2025 10-K (real inline-XBRL markup)."""
    res = parse("nvda_excerpt.htm")
    assert res["fallback"] is False
    assert {"1", "1A", "7", "7A"} <= set(res["items"])
    assert res["items"]["1A"]["heading"] == "Item 1A. Risk Factors"
    risk_titles = titles(res["items"]["1A"])
    assert risk_titles[1].startswith("Failure to meet the evolving needs of our industry")
    assert risk_titles[2] == ("Competition could adversely impact our market share and "
                              "financial results.")
    revenue = [s for s in res["items"]["7"]["sections"]
               if s["title"] == "Revenue by Reportable Segments"]
    assert revenue and revenue[0]["blocks"][0]["type"] == "table"
    assert "| Compute & Networking | $116,193 |" in revenue[0]["blocks"][0]["text"]


def test_parse_filing_and_main_write_json(tmp_path, monkeypatch):
    rec = {"ticker": "ACME", "cik": "0000012345", "company": "Acme", "sector": "x",
           "fiscal_year": 2024, "period_end": "2024-12-31", "accession_no": "ACC-1",
           "source_url": "https://www.sec.gov/acme.htm",
           "path": str(FIX / "synthetic_10k.htm")}
    manifest = tmp_path / "manifest.jsonl"
    manifest.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    from src.ingest import download_filings

    monkeypatch.setattr(download_filings, "MANIFEST", manifest)
    monkeypatch.setattr(ps, "SECTIONS_DIR", tmp_path / "sections")
    ps.main()
    out = json.loads((tmp_path / "sections" / "ACC-1.json").read_text(encoding="utf-8"))
    assert out["ticker"] == "ACME" and out["source_url"] == rec["source_url"]
    assert out["fallback"] is False and "1A" in out["items"]


# --- real filings (integration: only when the downloaded samples exist) -----------------

REAL = DATA_DIR / "raw" / "filings"
SAMPLES = {"NVDA": "0001045810-25-000023", "QCOM": "0000804328-24-000075",
           "PFE": "0000078003-25-000054", "JPM": "0000019617-25-000270"}


@pytest.mark.integration
@pytest.mark.parametrize("ticker", list(SAMPLES))
def test_real_filing_items_found(ticker):
    path = REAL / ticker / f"{SAMPLES[ticker]}.htm"
    if not path.exists():
        pytest.skip(f"{path} not downloaded")
    res = ps.parse_html(path.read_bytes(), SAMPLES[ticker])
    assert res["fallback"] is False
    assert {"1", "1A", "7"} <= set(res["items"])
    assert len(res["items"]["1A"]["sections"]) >= 20      # one section per risk factor
    assert res["items"]["7"]["cross_reference"] is (ticker == "JPM")
