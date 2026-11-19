"""Fast path unit tests (FR-18) with sql_tool stubbed (no database)."""

import pytest

from src.agent import fast_path
from src.agent.router import FactQuery, Route
from src.api.schemas import Tokens
from src.tools.types import Source, ToolResult, edgar_index_url

ACCN = "0000050863-25-000009"
ROW = {"value": 16_546_000_000.0, "period_end": "2024-12-28",
       "xbrl_tag": "ResearchAndDevelopmentExpense", "accession_no": ACCN, "name": "Intel",
       "source_id": f"xbrl:{ACCN}"}
SOURCE = Source(source_id=f"xbrl:{ACCN}", kind="xbrl", ticker="INTC", form="10-K",
                fiscal_year=2024, section="Item 8 Financial Statements (XBRL)",
                url=edgar_index_url("0000050863", ACCN), accession_no=ACCN)
INTEL_RD = Route(kind="fast", query=FactQuery("INTC", "rd_expense", 2024),
                 reason="single fact", tokens=Tokens(prompt=5, completion=3))


@pytest.fixture
def sql(monkeypatch):
    state = {"result": ToolResult(ok=True, data=[ROW], sources=[SOURCE]), "calls": []}

    def fake_call(sql):
        state["calls"].append(sql)
        return state["result"]

    monkeypatch.setattr(fast_path.sql_tool, "call", fake_call)
    return state


def test_answer_text_citation_steps_tokens(sql):
    resp = fast_path.answer("What was Intel's R&D in FY2024?", INTEL_RD)
    assert resp.answer == ("Intel's R&D expense for fiscal year 2024 (period ending "
                           "2024-12-28) was $16.55 billion.")
    [c] = resp.citations
    assert (c.ticker, c.form, c.fiscal_year, c.accession_no) == ("INTC", "10-K", 2024, ACCN)
    assert c.url == ("https://www.sec.gov/Archives/edgar/data/50863/000005086325000009/"
                     "0000050863-25-000009-index.htm")
    assert [s.name for s in resp.steps] == ["route", "sql_query"]
    assert resp.steps[0].detail["ticker"] == "INTC"
    assert resp.tokens == Tokens(prompt=5, completion=3)
    assert isinstance(resp.latency_ms, int) and resp.latency_ms >= 0
    assert len(sql["calls"]) == 1   # exactly one tool call


def test_sql_is_fixed_template_without_user_text(sql):
    question = "What was Intel's R&D in FY2024?'; DROP TABLE companies; --"
    fast_path.answer(question, INTEL_RD)
    [stmt] = sql["calls"]
    assert stmt == ("SELECT f.value, f.period_end, f.xbrl_tag, f.accession_no, c.name "
                    "FROM financial_facts f JOIN companies c ON c.ticker = f.ticker "
                    "WHERE f.ticker = 'INTC' AND f.metric = 'rd_expense' "
                    "AND f.fiscal_year = 2024")
    assert "DROP" not in stmt and "Intel's" not in stmt
    fast_path.sql_tool.check_select(stmt)   # passes the real read-only guard


@pytest.mark.parametrize("q", [
    FactQuery("INTC' OR '1'='1", "revenue", 2024),
    FactQuery("intc", "revenue", 2024),
    FactQuery("AAPL", "revenue", 2024),          # well-formed but not one of the 50
    FactQuery("INTC", "revenue'; --", 2024),
    FactQuery("INTC", "eps", 2024),
    FactQuery("INTC", "revenue", "2024"),
    FactQuery("INTC", "revenue", True),
])
def test_build_sql_rejects_values_outside_closed_sets(q):
    with pytest.raises(ValueError):
        fast_path.build_sql(q)


def test_not_found_when_no_row(sql):
    sql["result"] = ToolResult(ok=True, data=[], sources=[])
    r = Route(kind="fast", query=FactQuery("NVDA", "revenue", 2030))
    resp = fast_path.answer("What was NVIDIA's revenue in FY2030?", r)
    assert resp.answer == fast_path.NOT_FOUND == "Not found in the filings."
    assert resp.citations == []
    assert [s.name for s in resp.steps] == ["route", "sql_query"]


def test_not_found_on_tool_error(sql):
    sql["result"] = ToolResult.fail("database error: timeout")
    resp = fast_path.answer("x", INTEL_RD)
    assert resp.answer == fast_path.NOT_FOUND and resp.citations == []
    assert resp.steps[1].detail["error"] == "database error: timeout"


def test_not_found_when_row_has_no_citable_source(sql):
    sql["result"] = ToolResult(ok=True, data=[ROW], sources=[])
    assert fast_path.answer("x", INTEL_RD).answer == fast_path.NOT_FOUND


def test_negative_value_reads_naturally(sql):
    sql["result"] = ToolResult(ok=True, data=[{**ROW, "value": -18_756_000_000.0}],
                               sources=[SOURCE])
    r = Route(kind="fast", query=FactQuery("INTC", "net_income", 2024))
    resp = fast_path.answer("Intel net income 2024", r)
    assert resp.answer == ("Intel's net income for fiscal year 2024 (period ending "
                           "2024-12-28) was -$18.76 billion.")


@pytest.mark.parametrize("value,text", [
    (16_546_000_000, "$16.55 billion"), (2_500_000, "$2.50 million"), (950, "$950"),
    (-18_756_000_000, "-$18.76 billion"), (-2_500_000, "-$2.50 million"), (0, "$0"),
])
def test_format_usd(value, text):
    assert fast_path.format_usd(value) == text


def test_agent_route_is_rejected():
    with pytest.raises(ValueError):
        fast_path.answer("x", Route(kind="agent", reason="multi-hop"))
