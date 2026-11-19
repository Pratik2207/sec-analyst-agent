"""Hardening decided after the Phase 2 review: SEC name validation, response cap,
tuple/set filters, embed-before-delete re-index."""

import httpx
import pytest
from qdrant_client import models

from src import sec_client
from src.ingest import download_filings as df
from src.retrieval.hybrid_search import build_filter
from src.retrieval.types import SearchFilters
from src.sec_client import SecClient


def _client(handler):
    return SecClient("test test@example.com", 1000, transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("name", ["../../evil.json", "C:\\x.json", "CIK1-submissions-001.json",
                                  "/etc/passwd"])
def test_bad_submissions_page_name_rejected_and_nothing_written(tmp_path, name):
    sub = {"filings": {"recent": {"accessionNumber": [], "primaryDocument": []},
                       "files": [{"name": name}]}}
    client = _client(lambda r: httpx.Response(200, json=sub))
    with pytest.raises(ValueError, match="submissions page"):
        df.primary_document(client, "1", "0000000001-25-000001", tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["CIK0000000001.json"]


@pytest.mark.parametrize("doc", ["../x.htm", "a/b.htm", "..htm", "x.htm?y=1"])
def test_bad_primary_document_rejected(tmp_path, doc):
    accn = "0000000001-25-000001"
    sub = {"filings": {"recent": {"accessionNumber": [accn], "primaryDocument": [doc]}}}
    client = _client(lambda r: httpx.Response(200, json=sub))
    with pytest.raises(ValueError, match="primaryDocument"):
        df.primary_document(client, "1", accn, tmp_path)


def test_real_shaped_names_accepted(tmp_path):
    accn = "0000019617-25-000270"
    page = {"accessionNumber": [accn], "primaryDocument": ["jpm-20241231.htm"]}
    sub = {"filings": {"recent": {"accessionNumber": [], "primaryDocument": []},
                       "files": [{"name": "CIK0000019617-submissions-001.json"}]}}

    def handler(r):
        return httpx.Response(200, json=page if "submissions-001" in str(r.url) else sub)

    assert df.primary_document(_client(handler), "19617", accn, tmp_path) == "jpm-20241231.htm"


def test_response_size_cap(monkeypatch):
    monkeypatch.setattr(sec_client, "MAX_BYTES", 1000)
    client = _client(lambda r: httpx.Response(200, content=b"x" * 5000))
    with pytest.raises(ValueError, match="exceeds"):
        client.get_bytes("https://www.sec.gov/x")


def test_tuple_and_set_filters_become_match_any():
    f = build_filter(SearchFilters(fiscal_year=(2024, 2025), ticker={"NVDA"}))
    by_key = {c.key: c.match for c in f.must}
    assert by_key["fiscal_year"] == models.MatchAny(any=[2024, 2025])
    assert by_key["ticker"] == models.MatchAny(any=["NVDA"])
