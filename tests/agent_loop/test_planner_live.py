"""The real planner on Ollama (needs Ollama only). Few calls: memory and GPU are tight.

Run with -s to see the plans, latency and tokens (the planner model measurement)."""

import time

import httpx
import pytest

from config.settings import get_settings
from src.agent import planner

pytestmark = pytest.mark.integration

SEMIS = ("Which semiconductor companies raised R&D as a share of revenue while gross margin "
         "fell, FY2024 to FY2025?")


@pytest.fixture(autouse=True)
def _ollama():
    try:
        httpx.get(get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")


def _run(monkeypatch, question, model=None, think=None):
    s = get_settings()
    if model is not None:
        monkeypatch.setattr(s, "planner_model", model)
        monkeypatch.setattr(s, "planner_think", think)
    t = time.perf_counter()
    steps, tokens = planner.plan(question)
    secs = time.perf_counter() - t
    print(f"\n[{s.planner_model} think={s.planner_think}] {secs:.1f}s "
          f"prompt={tokens.prompt} completion={tokens.completion}")
    for st in steps:
        print("  ", st.model_dump(exclude_defaults=True))
    return steps, tokens


def _check_semis(steps):
    sql = [s for s in steps if s.tool == "sql_query"]
    calcs = [s for s in steps if s.tool == "calculate"]
    assert sql and calcs
    fetched = {m for s in sql for m in s.metrics}
    assert {"rd_expense", "revenue", "gross_profit"} <= fetched
    assert {2024, 2025} <= {y for s in sql for y in s.fiscal_years}
    assert any("rd_expense" in c.expression for c in calcs)
    assert any("gross_profit" in c.expression for c in calcs)


@pytest.mark.parametrize("model,think", [("qwen3:4b-instruct", False), ("qwen3:4b", True)])
def test_semis_plan(monkeypatch, model, think):
    steps, _ = _run(monkeypatch, SEMIS, model, think)
    _check_semis(steps)


def test_text_question_plan(monkeypatch):
    steps, _ = _run(monkeypatch, "Why did AMD's gross margin fall in 2024?")
    search = [s for s in steps if s.tool == "search_filings"]
    assert search and search[0].tickers == ["AMD"]


def test_future_year_kept(monkeypatch):
    steps, _ = _run(monkeypatch, "What was NVIDIA's revenue in FY2030 and how did it grow?")
    assert any(s.tool == "sql_query" and 2030 in s.fiscal_years for s in steps)
