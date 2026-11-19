"""Planner validation and fallback, with chat_json stubbed."""

import pytest

from src.agent import planner
from src.agent.llm import LLMError
from src.agent.state import MAX_TOOL_CALLS, PlanStep
from src.api.schemas import Tokens

SQL = {"tool": "sql_query", "goal": "facts", "sector": "semiconductors",
       "metrics": ["rd_expense", "revenue", "gross_profit"], "fiscal_years": [2024, 2025]}
CALC = {"tool": "calculate", "goal": "share", "name": "rd_share_change",
        "expression": "rd_expense_2025/revenue_2025 - rd_expense_2024/revenue_2024"}


def test_valid_semis_plan_kept():
    steps = planner.normalise([SQL, CALC])
    assert [s.tool for s in steps] == ["sql_query", "calculate"]
    assert steps[0].fiscal_years == [2024, 2025] and steps[0].sector == "semiconductors"
    assert steps[1].name == "rd_share_change"


@pytest.mark.parametrize("bad", [
    "not a dict",
    {"tool": "drop_table", "goal": "x"},
    {"tool": "sql_query", "goal": "no metrics", "tickers": ["NVDA"]},
    {"tool": "sql_query", "goal": "no who", "metrics": ["revenue"]},
    {"tool": "sql_query", "goal": "unknown", "tickers": ["ZZZZ"], "metrics": ["ebitda"]},
    {"tool": "search_filings", "goal": "no query", "tickers": ["AMD"]},
    {"tool": "get_section", "goal": "no item", "tickers": ["AMD"], "fiscal_years": [2024]},
    {"tool": "calculate", "goal": "unfetched", "expression": "net_income_2025 / revenue_2025"},
    {"tool": "calculate", "goal": "unparsable", "expression": "rd_expense_2025 /"},
    {"tool": "calculate", "goal": "not a var", "expression": "__import__('os')"},
    {"tool": "calculate", "goal": "year not fetched", "expression": "revenue_2023 * 2"},
])
def test_bad_steps_dropped(bad):
    steps = planner.normalise([SQL, bad])
    assert [s.tool for s in steps] == ["sql_query"]


def test_llm_shaped_steps():
    """The schema's keys (about/action, every field present with ""/[] when unused)."""
    raw = [{"about": "facts", "action": "sql_query", "sector": "semiconductors",
            "tickers": ["NVDA", "AMD"], "metrics": ["revenue"], "fiscal_years": [2024],
            "query": "", "item": "", "expression": "", "name": ""},
           {"about": "x2", "action": "calculate", "sector": "", "tickers": ["NVDA"],
            "metrics": [], "fiscal_years": [], "query": "", "item": "",
            "expression": "revenue_2024 * 2", "name": "double"}]
    sql, calc = planner.normalise(raw)
    assert (sql.goal, sql.sector, sql.tickers, sql.item, sql.query) == (
        "facts", "semiconductors", [], None, None)    # the sector covers the tickers
    assert (calc.tool, calc.tickers, calc.sector, calc.name) == ("calculate", [], None,
                                                                 "double")


def test_calc_before_sql_dropped():
    assert [s.tool for s in planner.normalise([CALC, SQL])] == ["sql_query"]


def test_unknown_values_dropped_and_years_coerced():
    [s] = planner.normalise([{"tool": "sql_query", "goal": "g",
                              "tickers": ["nvda", "ZZZZ", "AMD", "NVDA"],
                              "sector": "Crypto", "metrics": ["revenue", "ebitda"],
                              "fiscal_years": [2024.0, "2025", 2024.5, True, 99999, None]}])
    assert s.tickers == ["NVDA", "AMD"]
    assert s.sector is None
    assert s.metrics == ["revenue"]
    assert s.fiscal_years == [2024, 2025]
    assert all(type(y) is int for y in s.fiscal_years)


def test_search_split_per_ticker_and_multi_year_unfiltered():
    steps = planner.normalise([{"tool": "search_filings", "goal": "risks", "query": "supply",
                                "tickers": ["INTC", "QCOM"], "fiscal_years": [2024, 2025],
                                "item": "1a"}])
    assert [(s.tickers, s.fiscal_years, s.item) for s in steps] == [
        (["INTC"], [], "1A"), (["QCOM"], [], "1A")]


def test_duplicates_removed_and_plan_capped():
    raw = [SQL, SQL] + [{"tool": "search_filings", "goal": "g", "query": f"q{i}"}
                        for i in range(20)]
    steps = planner.normalise(raw)
    assert len(steps) == MAX_TOOL_CALLS
    assert len({s.signature() for s in steps}) == len(steps)


def test_schema_uses_enums():
    item = planner.SCHEMA["properties"]["steps"]["items"]["properties"]
    assert set(item["tickers"]["items"]["enum"]) == set(planner.TICKERS)
    assert len(planner.TICKERS) == 50
    assert set(item["metrics"]["items"]["enum"]) == set(planner.METRICS)
    assert item["sector"]["enum"] == [*planner.SECTORS, ""]
    assert item["item"]["enum"] == ["1", "1A", "7", "7A", ""]
    assert set(planner.SCHEMA["properties"]["steps"]["items"]["required"]) == set(item)
    assert list(item)[:2] == ["about", "action"] and sorted(item)[:2] == ["about", "action"]
    assert set(item["action"]["enum"]) == {"sql_query", "search_filings", "get_section",
                                         "calculate", "list_companies"}


def test_system_prompt_filled():
    p = planner.system_prompt()
    assert "{companies}" not in p and "{sector_metrics}" not in p
    assert "NVDA: NVIDIA (semiconductors)" in p
    assert "banks: revenue, net_income, total_assets (NO gross_profit, rd_expense" in p
    assert "rd_share_change" in p


def _stub_llm(monkeypatch, reply):
    calls = []

    def fake(model, system, user, schema, think=False):
        calls.append({"model": model, "user": user, "think": think})
        if isinstance(reply, Exception):
            raise reply
        return reply, Tokens(prompt=100, completion=20)

    monkeypatch.setattr(planner, "chat_json", fake)
    return calls


def test_plan_uses_settings_model(monkeypatch):
    calls = _stub_llm(monkeypatch, {"steps": [SQL, CALC]})
    steps, tokens = planner.plan("semis question")
    s = planner.get_settings()
    assert calls == [{"model": s.planner_model, "user": "semis question",
                      "think": s.planner_think}]
    assert len(steps) == 2 and tokens == Tokens(prompt=100, completion=20)


@pytest.mark.parametrize("reply", [LLMError("down"), {"steps": "nonsense"}, {"x": 1}, [1]])
def test_fallback_plan(monkeypatch, reply):
    _stub_llm(monkeypatch, reply)
    steps, _ = planner.plan("Why did AMD's gross margin fall?")
    assert steps == [PlanStep(tool="search_filings",
                              goal="find passages that answer the question",
                              query="Why did AMD's gross margin fall?")]
