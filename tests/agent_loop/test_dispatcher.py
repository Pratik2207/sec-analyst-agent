"""Dispatcher: code-built SQL and per-ticker calculate, with tools stubbed."""

import pytest

from src.agent import graph
from src.agent.state import PlanStep
from src.tools import sql_tool
from src.tools.types import ToolResult
from tests.agent_loop.helpers import SEMIS_FACTS, accn, sql_result


def test_sql_sector_query():
    step = PlanStep(tool="sql_query", goal="Which chip firms'; DROP TABLE companies; --",
                    sector="semiconductors", metrics=["rd_expense", "revenue"],
                    fiscal_years=[2024, 2025])
    sql = graph.build_sql(step)
    assert sql == ("SELECT f.ticker, f.fiscal_year, f.period_end, f.metric, f.value, "
                   "f.accession_no FROM financial_facts f JOIN companies c ON c.ticker = "
                   "f.ticker WHERE c.sector = 'semiconductors' AND f.metric IN "
                   "('rd_expense', 'revenue') AND f.fiscal_year IN (2024, 2025) "
                   "ORDER BY f.ticker, f.metric, f.fiscal_year")
    assert "DROP" not in sql
    sql_tool.check_select(sql)


def test_sql_ticker_query():
    step = PlanStep(tool="sql_query", goal="g", tickers=["NVDA", "AMD"], metrics=["revenue"])
    sql = graph.build_sql(step)
    assert "JOIN" not in sql and "f.ticker IN ('NVDA', 'AMD')" in sql
    assert "fiscal_year IN" not in sql and "f.accession_no" in sql
    sql_tool.check_select(sql)


@pytest.mark.parametrize("bad", [
    {"tickers": ["NVDA' OR '1'='1"], "metrics": ["revenue"]},
    {"tickers": ["ZZZ"], "metrics": ["revenue"]},
    {"sector": "x' OR 1=1 --", "metrics": ["revenue"]},
    {"tickers": ["NVDA"], "metrics": ["revenue'; --"]},
    {"tickers": ["NVDA"], "metrics": []},
    {"metrics": ["revenue"]},
    {"tickers": ["NVDA"], "metrics": ["revenue"], "fiscal_years": [2024.0]},
    {"tickers": ["NVDA"], "metrics": ["revenue"], "fiscal_years": ["2024 OR 1=1"]},
    {"tickers": "NVDA", "metrics": ["revenue"]},
])
def test_bad_sql_args_become_failed_result(monkeypatch, bad):
    monkeypatch.setattr(graph.sql_tool, "call", lambda sql: pytest.fail("must not run"))
    step = PlanStep.model_construct(tool="sql_query", goal="g", **{
        "tickers": [], "sector": None, "metrics": [], "fiscal_years": [], **bad})
    res, _ = graph.dispatch(step, [])
    assert not res.ok and "bad arguments" in res.error


def test_sql_dispatch_calls_tool(monkeypatch):
    calls = []
    monkeypatch.setattr(graph.sql_tool, "call",
                        lambda sql: calls.append(sql) or ToolResult(ok=True))
    step = PlanStep(tool="sql_query", goal="g", tickers=["NVDA"], metrics=["revenue"],
                    fiscal_years=[2024])
    res, extra = graph.dispatch(step, [])
    assert res.ok and calls == [extra["sql"]]


def test_calculate_per_ticker():
    prior = [ToolResult.fail("earlier failure"), sql_result(SEMIS_FACTS)]
    step = PlanStep(tool="calculate", goal="g", name="gross_margin_change",
                    expression="gross_profit_2025/revenue_2025 - gross_profit_2024/revenue_2024")
    res, extra = graph.dispatch(step, prior)
    assert res.ok
    [d] = res.data                     # INTC lacks gross_profit_2025
    assert d["ticker"] == "NVDA" and d["name"] == "gross_margin_change"
    assert d["values"] == {"gross_profit_2025": 97_858e6, "revenue_2025": 130_497e6,
                           "gross_profit_2024": 44_301e6, "revenue_2024": 60_922e6}
    assert d["result"] == pytest.approx(97_858 / 130_497 - 44_301 / 60_922)
    assert d["input_source_ids"] == sorted({f"xbrl:{accn('NVDA', 2024)}",
                                            f"xbrl:{accn('NVDA', 2025)}"})
    assert d["source_id"].startswith("calc:") and res.source(d["source_id"]).kind == "calc"
    assert extra["notes"] == ["INTC: missing gross_profit_2025"]


def test_calculate_two_tickers_merged_into_one_result():
    step = PlanStep(tool="calculate", goal="g", name="rd_share_2025",
                    expression="rd_expense_2025 / revenue_2025 * 100")
    res, _ = graph.dispatch(step, [sql_result(SEMIS_FACTS)])
    assert [d["ticker"] for d in res.data] == ["NVDA", "INTC"]
    assert len({d["source_id"] for d in res.data}) == 2
    assert {s.source_id for s in res.sources} == {d["source_id"] for d in res.data}
    assert res.data[1]["result"] == pytest.approx(13_000 / 52_000 * 100)


def test_calculate_without_inputs_fails():
    step = PlanStep(tool="calculate", goal="g", expression="net_income_2025 * 2")
    res, _ = graph.dispatch(step, [sql_result(SEMIS_FACTS)])
    assert not res.ok and "no company had all inputs" in res.error


def test_calculate_bad_expression_type_fails():
    step = PlanStep.model_construct(tool="calculate", goal="g", tickers=[], expression=42,
                                    name=None)
    res, _ = graph.dispatch(step, [sql_result(SEMIS_FACTS)])
    assert not res.ok and "bad arguments" in res.error


def test_search_and_section_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(graph.search_tool, "call",
                        lambda **kw: seen.setdefault("search", kw) and ToolResult(ok=True))
    monkeypatch.setattr(graph.section_tool, "call",
                        lambda *a: seen.setdefault("section", a) and ToolResult(ok=True))
    graph.dispatch(PlanStep(tool="search_filings", goal="g", query="risks", tickers=["AMD"],
                            fiscal_years=[2024], item="1A"), [])
    assert seen["search"] == {"query": "risks", "ticker": "AMD", "sector": None,
                              "fiscal_year": 2024, "item": "1A"}
    graph.dispatch(PlanStep(tool="get_section", goal="g", tickers=["AMD"],
                            fiscal_years=[2024], item="7"), [])
    assert seen["section"] == ("AMD", 2024, "7")
    res, _ = graph.dispatch(PlanStep(tool="get_section", goal="g", tickers=["AMD"]), [])
    assert not res.ok and "bad arguments" in res.error


def test_tool_type_error_becomes_failed_result(monkeypatch):
    def broken(**kw):
        raise TypeError("unexpected keyword")
    monkeypatch.setattr(graph.search_tool, "call", broken)
    res, _ = graph.dispatch(PlanStep(tool="search_filings", goal="g", query="x"), [])
    assert not res.ok and "TypeError" in res.error
