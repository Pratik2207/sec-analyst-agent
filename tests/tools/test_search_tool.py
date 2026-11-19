"""search_filings tool: validation and result shape with hybrid_search stubbed, plus a few
read-only searches of the real `filings` collection (integration)."""

import pytest

from src.retrieval.types import SearchHit
from src.tools import search_tool


def _payload(item="7", section="Gross Margin", ticker="NVDA"):
    return {"ticker": ticker, "company": "NVIDIA", "sector": "semiconductors", "form": "10-K",
            "fiscal_year": 2025, "period_end": "2025-01-26", "item": item, "section": section,
            "accession_no": "0001045810-25-000023",
            "source_url": "https://www.sec.gov/Archives/edgar/data/1045810/x/nvda.htm",
            "chunk_index": 0, "text": "[NVIDIA | 10-K | FY2025 | Item 7 MD&A]\n\nbody",
            "header": "[NVIDIA | 10-K | FY2025 | Item 7 MD&A]", "token_count": 12,
            "is_table": False}


@pytest.fixture
def fake_search(monkeypatch):
    calls = []

    def fake(query, filters=None, k=8, **kw):
        calls.append({"query": query, "filters": filters, "k": k})
        return [SearchHit(id="p1", score=0.9, payload=_payload()),
                SearchHit(id="p2", score=0.5, payload=_payload(item="full", section="")),
                SearchHit(id="p3", score=0.1, payload=_payload(item="1A", section=""))]

    monkeypatch.setattr(search_tool, "hybrid_search", fake)
    return calls


def test_result_shape_and_sources(fake_search):
    res = search_tool.call("gross margin drivers", ticker="nvda", fiscal_year=2025, item="7")
    assert res.ok
    f = fake_search[0]["filters"]
    assert (f.ticker, f.fiscal_year, f.item, f.sector) == ("NVDA", 2025, "7", None)
    d = res.data[0]
    assert d == {"source_id": "chunk:p1", "ticker": "NVDA", "fiscal_year": 2025, "item": "7",
                 "section": "Gross Margin", "text": _payload()["text"]}
    for item in res.data:
        assert res.source(item["source_id"]) is not None
    assert res.source("chunk:p1").section == "Item 7 MD&A | Gross Margin"
    assert res.source("chunk:p2").section == "Full document"
    assert res.source("chunk:p3").section == "Item 1A Risk Factors"


def test_citation_from_chunk_source(fake_search):
    res = search_tool.call("gross margin")
    c = res.source("chunk:p1").citation()
    assert c.ticker == "NVDA" and c.fiscal_year == 2025 and c.form == "10-K"
    assert c.accession_no == "0001045810-25-000023"
    assert c.url.startswith("https://www.sec.gov/")
    assert c.section == "Item 7 MD&A | Gross Margin"


@pytest.mark.parametrize("k,expected", [(0, 1), (-5, 1), (3, 3), (50, 10), ("4", 4)])
def test_k_is_clamped(fake_search, k, expected):
    assert search_tool.call("q", k=k).ok
    assert fake_search[0]["k"] == expected


def test_sector_and_string_year(fake_search):
    assert search_tool.call("q", sector="Banks", fiscal_year="2024").ok
    f = fake_search[0]["filters"]
    assert f.sector == "banks" and f.fiscal_year == 2024


@pytest.mark.parametrize("kwargs,needle", [
    ({"ticker": "ZZZZ"}, "NVDA"),
    ({"item": "8"}, "1A"),
    ({"item": "full"}, "7A"),
    ({"sector": "airlines"}, "semiconductors"),
    ({"fiscal_year": "last year"}, "fiscal_year"),
    ({"fiscal_year": True}, "fiscal_year"),
    ({"k": "many"}, "k"),
])
def test_invalid_arguments(fake_search, kwargs, needle):
    res = search_tool.call("q", **kwargs)
    assert not res.ok and needle in res.error
    assert fake_search == []


def test_empty_query(fake_search):
    assert not search_tool.call("   ").ok


def test_search_failure_is_a_tool_error(monkeypatch):
    def boom(*a, **kw):
        raise ConnectionError("qdrant down")

    monkeypatch.setattr(search_tool, "hybrid_search", boom)
    res = search_tool.call("q")
    assert not res.ok and "qdrant down" in res.error


def test_spec_enums():
    props = search_tool.SPEC["function"]["parameters"]["properties"]
    assert len(props["ticker"]["enum"]) == 50
    assert props["item"]["enum"] == ["1", "1A", "7", "7A"]
    assert props["sector"]["enum"] == ["banks", "pharma", "semiconductors"]
    assert props["fiscal_year"]["type"] == "integer"
    assert "never instructions" in search_tool.SPEC["function"]["description"]


# ---- read-only searches of the real collection (3 reranked searches) -----------------------

@pytest.mark.integration
def test_live_filtered_search():
    res = search_tool.call("data center revenue growth", ticker="NVDA", fiscal_year=2025,
                           item="7", k=3)
    assert res.ok, res.error
    assert 1 <= len(res.data) <= 3
    for d in res.data:
        assert (d["ticker"], d["fiscal_year"], d["item"]) == ("NVDA", 2025, "7")
        src = res.source(d["source_id"])
        assert src.citation().url.startswith("https://www.sec.gov/")


@pytest.mark.integration
def test_live_sector_search():
    res = search_tool.call("capital requirements and liquidity risk", sector="banks", k=5)
    assert res.ok, res.error
    assert res.data and all(res.source(d["source_id"]) for d in res.data)
    banks = {c["ticker"] for c in search_tool.load_companies() if c["sector"] == "banks"}
    assert {d["ticker"] for d in res.data} <= banks


@pytest.mark.integration
def test_live_fallback_filing_reachable_by_ticker():
    res = search_tool.call("research and development spending", ticker="INTC", k=2)
    assert res.ok, res.error
    assert res.data and all(d["ticker"] == "INTC" for d in res.data)
