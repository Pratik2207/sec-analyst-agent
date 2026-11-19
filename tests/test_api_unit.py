"""Phase 1 tester: /ask unit tests with the LLM and the DB stubbed (FR-8 citations, X-3)."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api import main
from src.api.schemas import Tokens


def test_edgar_url_format():
    assert main.edgar_url("0000050863", "0000050863-25-000009") == (
        "https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/"
        "0000050863-25-000009-index.htm")


@pytest.mark.parametrize("value,text", [
    (16_546_000_000, "$16.55 billion"), (2_500_000, "$2.50 million"), (950, "$950"),
])
def test_format_usd(value, text):
    assert main.format_usd(value) == text


def test_format_usd_negative_reads_naturally():
    # a net loss (e.g. Intel FY2024 net income) should not render as "$-18.76 billion"
    assert main.format_usd(-18_756_000_000) in ("-$18.76 billion", "($18.76 billion)")


ROW = {"value": 16_546_000_000.0, "period_end": "2024-12-28",
       "xbrl_tag": "ResearchAndDevelopmentExpense", "accession_no": "0000050863-25-000009",
       "cik": "0000050863", "name": "Intel"}


@pytest.fixture
def stub(monkeypatch):
    state = {"query": {"ticker": "INTC", "metric": "rd_expense", "fiscal_year": 2024},
             "rows": [ROW], "calls": []}

    def fake_run(sql, params=None, **_):
        state["calls"].append((sql, params))
        if "financial_facts" not in sql:
            return {"ok": True, "rows": [{"ticker": "INTC", "name": "Intel"}], "error": None}
        return {"ok": True, "rows": state["rows"], "error": None}

    monkeypatch.setattr(main.sql_tool, "run", fake_run)
    monkeypatch.setattr(main, "extract_query",
                        lambda q, c, m: (state["query"], Tokens(prompt=5, completion=3)))
    return state


def test_ask_happy_path_cites_ticker_form_fy_accession_url(stub):
    r = TestClient(main.app).post("/ask", json={"question": "Intel R&D FY2024?"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == ("Intel's R&D expense for fiscal year 2024 (period ending "
                              "2024-12-28) was $16.55 billion.")
    [c] = body["citations"]
    assert c["ticker"] == "INTC" and c["form"] == "10-K" and c["fiscal_year"] == 2024
    assert c["accession_no"] == ROW["accession_no"]
    assert c["url"] == main.edgar_url(ROW["cik"], ROW["accession_no"])
    assert [s["name"] for s in body["steps"]] == ["extract", "sql_query"]
    assert body["tokens"] == {"prompt": 5, "completion": 3}
    assert isinstance(body["latency_ms"], int)
    # SQL is parameterised, never string-formatted with LLM output
    sql, params = stub["calls"][-1]
    assert params == ("INTC", "rd_expense", 2024) and "INTC" not in sql


@pytest.mark.parametrize("query", [
    {"ticker": "NONE", "metric": "revenue", "fiscal_year": 2024},
    {"ticker": "INTC", "metric": "NONE", "fiscal_year": 2024},
    {"ticker": "INTC", "metric": "revenue", "fiscal_year": 0},
])
def test_ask_not_found_when_extraction_incomplete(stub, query):
    stub["query"] = query
    body = TestClient(main.app).post("/ask", json={"question": "x"}).json()
    assert body["answer"] == main.NOT_FOUND and body["citations"] == []


def test_ask_not_found_when_no_rows(stub):
    stub["rows"] = []
    body = TestClient(main.app).post("/ask", json={"question": "x"}).json()
    assert body["answer"] == main.NOT_FOUND and body["citations"] == []


@pytest.mark.parametrize("payload", [{"question": ""}, {}, {"question": "x" * 2001}])
def test_ask_rejects_bad_requests(payload):
    assert TestClient(main.app).post("/ask", json=payload).status_code == 422


def test_extract_query_uses_configured_fast_model_and_schema(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, host):
            seen["host"] = host

        def chat(self, **kw):
            seen.update(kw)
            return SimpleNamespace(
                message=SimpleNamespace(
                    content='{"ticker": "INTC", "metric": "rd_expense", "fiscal_year": 2024}'),
                prompt_eval_count=11, eval_count=7)

    monkeypatch.setattr(main.ollama, "Client", FakeClient)
    q, tokens = main.extract_query("Intel R&D 2024", [{"ticker": "INTC", "name": "Intel"}],
                                   ["revenue", "rd_expense"])
    s = main.get_settings()
    assert q == {"ticker": "INTC", "metric": "rd_expense", "fiscal_year": 2024}
    assert tokens == Tokens(prompt=11, completion=7)
    assert seen["model"] == s.fast_model and seen["host"] == s.ollama_host
    props = seen["format"]["properties"]
    assert props["ticker"]["enum"] == ["INTC", "NONE"]
    assert props["metric"]["enum"] == ["revenue", "rd_expense", "NONE"]
