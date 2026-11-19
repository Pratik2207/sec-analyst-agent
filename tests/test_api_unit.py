"""/ask wiring (Phase 3): router -> fast path or agent placeholder, with the LLM and DB
stubbed. Routing and fast-path details are tested in tests/agent_fast/."""

import pytest
from fastapi.testclient import TestClient

from src.agent import fast_path, router
from src.agent.router import FactQuery, Route
from src.api import main
from src.api.schemas import Tokens
from src.tools import sql_tool
from src.tools.types import Source, ToolResult, edgar_index_url

ACCN = "0000050863-25-000009"
ROW = {"name": "Intel", "value": 16_546_000_000.0, "period_end": "2024-12-28",
       "xbrl_tag": "ResearchAndDevelopmentExpense", "accession_no": ACCN,
       "source_id": f"xbrl:{ACCN}"}
SOURCE = Source(source_id=f"xbrl:{ACCN}", kind="xbrl", ticker="INTC", form="10-K",
                fiscal_year=2024, section="Item 8 Financial Statements (XBRL)",
                url=edgar_index_url("0000050863", ACCN), accession_no=ACCN)


def test_edgar_index_url_format():
    assert edgar_index_url("0000050863", ACCN) == (
        "https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/"
        "0000050863-25-000009-index.htm")


@pytest.fixture
def fast(monkeypatch):
    state = {"rows": [ROW], "sql": []}
    monkeypatch.setattr(router, "route", lambda q: Route(
        "fast", FactQuery("INTC", "rd_expense", 2024), "single fact", Tokens(prompt=5,
                                                                             completion=3)))

    def fake_call(sql):
        state["sql"].append(sql)
        return ToolResult(ok=True, data=state["rows"], sources=[SOURCE] if state["rows"] else [])

    monkeypatch.setattr(sql_tool, "call", fake_call)
    return state


def test_fast_route_answers_with_citation(fast):
    body = TestClient(main.app).post("/ask", json={"question": "Intel R&D FY2024?"}).json()
    assert body["answer"] == ("Intel's R&D expense for fiscal year 2024 (period ending "
                              "2024-12-28) was $16.55 billion.")
    [c] = body["citations"]
    assert (c["ticker"], c["form"], c["fiscal_year"], c["accession_no"]) == (
        "INTC", "10-K", 2024, ACCN)
    assert c["url"] == SOURCE.url
    assert [s["name"] for s in body["steps"]] == ["route", "sql_query"]
    assert body["tokens"] == {"prompt": 5, "completion": 3}
    assert isinstance(body["latency_ms"], int)


def test_fast_route_not_found_when_no_rows(fast):
    fast["rows"] = []
    body = TestClient(main.app).post("/ask", json={"question": "x"}).json()
    assert body["answer"] == fast_path.NOT_FOUND and body["citations"] == []


def test_agent_route_returns_placeholder(monkeypatch):
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="multi-hop"))
    body = TestClient(main.app).post("/ask", json={"question": "Which chip makers..."}).json()
    assert body["answer"] == main.AGENT_PENDING and body["citations"] == []
    assert body["steps"][0]["detail"] == {"kind": "agent", "reason": "multi-hop"}


def test_latency_includes_routing(monkeypatch):
    import time

    def slow_route(q):
        time.sleep(0.05)
        return Route("agent", reason="x")

    monkeypatch.setattr(router, "route", slow_route)
    body = TestClient(main.app).post("/ask", json={"question": "q"}).json()
    assert body["latency_ms"] >= 50


@pytest.mark.parametrize("payload", [{"question": ""}, {}, {"question": "x" * 2001}])
def test_ask_rejects_bad_requests(payload):
    assert TestClient(main.app).post("/ask", json=payload).status_code == 422
