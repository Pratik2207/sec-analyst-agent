"""Router unit tests (FR-18) with the LLM stubbed."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agent import router
from src.api.schemas import Tokens

CASES = [json.loads(line) for line in
         (Path(__file__).parent / "router_cases.jsonl").read_text(encoding="utf-8").splitlines()
         if line.strip()]


def test_fixture_set_is_balanced_and_covers_acceptance_questions():
    kinds = [c["kind"] for c in CASES]
    assert len(CASES) >= 24 and abs(kinds.count("fast") - kinds.count("agent")) <= 3
    qs = {c["q"]: c["kind"] for c in CASES}
    assert qs["What was Intel's R&D in FY2024?"] == "fast"
    assert qs["Which semiconductor companies raised R&D as a share of revenue while gross "
              "margin fell, FY2024 to FY2025?"] == "agent"


@pytest.fixture
def fake_llm(monkeypatch):
    """Stub extract(): a perfect extractor driven by the fixture labels."""
    calls = []
    labels = {c["q"]: c for c in CASES}

    def fake_extract(question):
        calls.append(question)
        c = labels.get(question, {})
        if c.get("kind") == "fast":
            q = {k: c[k] for k in ("ticker", "metric", "fiscal_year")}
        else:
            q = {"ticker": "NONE", "metric": "NONE", "fiscal_year": 0}
        return q, Tokens(prompt=100, completion=20)

    monkeypatch.setattr(router, "extract", fake_extract)
    return calls


@pytest.mark.parametrize("case", CASES, ids=[c["q"][:50] for c in CASES])
def test_fixture_routing_with_stubbed_llm(fake_llm, case):
    r = router.route(case["q"])
    assert r.kind == case["kind"], r.reason
    if case["kind"] == "fast":
        assert r.query == router.FactQuery(case["ticker"], case["metric"], case["fiscal_year"])
        assert r.tokens == Tokens(prompt=100, completion=20)
    # cheap rules decide every agent case except the ones only the LLM can judge
    llm_needed = case["kind"] == "fast" or case.get("llm", False)
    assert (fake_llm == [case["q"]]) == llm_needed
    if not llm_needed:
        assert r.tokens == Tokens() and r.reason


@pytest.mark.parametrize("q,years", [
    ("Intel R&D FY2024", [2024]), ("Intel R&D FY 2024", [2024]), ("Intel R&D FY24", [2024]),
    ("Intel R&D fiscal 2025", [2025]), ("in 2023", [2023]), ("2024 and 2025", [2024, 2025]),
    ("FY2024 to FY2025", [2024, 2025]), ("2024 vs 2024", [2024]), ("Revenue of AMD?", []),
    ("its 10-K", []), ("$12024", []),
])
def test_find_years(q, years):
    assert router.find_years(q) == years


@pytest.mark.parametrize("q,tickers", [
    ("What was Intel's R&D?", ["INTC"]),
    ("INTC revenue", ["INTC"]),
    ("Compare NVDA and AMD", ["NVDA", "AMD"]),
    ("JPMorgan total assets", ["JPM"]),
    ("JPMorgan Chase total assets", ["JPM"]),
    ("Lilly revenue", ["LLY"]),
    ("Eli Lilly revenue", ["LLY"]),
    ("Bank of America total assets", ["BAC"]),
    ("nvidia revenue", ["NVDA"]),
    ("Morgan Stanley net income", ["MS"]),
    ("NXP Semiconductors revenue", ["NXPI"]),
    # lowercase common words are not tickers (ON, C, KEY, MS, ...)
    ("what is the key number on revenue for c", []),
    ("What was Apple's revenue?", []),
    ("R&D at S&P companies", []),
])
def test_find_companies(q, tickers):
    assert router.find_companies(q) == tickers


def test_company_name_is_not_a_sector_word():
    assert router.rule_check("What was NXP Semiconductors' revenue in 2024?")[0] is None
    assert "sector" in router.rule_check("Semiconductor revenue for NVIDIA in 2024")[0]


def test_llm_ticker_or_year_disagreeing_with_code_goes_to_agent(monkeypatch):
    monkeypatch.setattr(router, "extract", lambda q: (
        {"ticker": "AMD", "metric": "revenue", "fiscal_year": 2024}, Tokens(prompt=1)))
    r = router.route("What was Intel's revenue in 2024?")
    assert r.kind == "agent" and "disagrees" in r.reason and r.tokens.prompt == 1
    monkeypatch.setattr(router, "extract", lambda q: (
        {"ticker": "INTC", "metric": "revenue", "fiscal_year": 2023}, Tokens()))
    assert router.route("What was Intel's revenue in 2024?").kind == "agent"


def test_llm_failure_goes_to_agent(monkeypatch):
    def boom(q):
        raise ConnectionError("ollama down")
    monkeypatch.setattr(router, "extract", boom)
    r = router.route("What was Intel's revenue in 2024?")
    assert r.kind == "agent" and "extraction failed" in r.reason


def test_extract_uses_fast_model_schema_and_thinking_off(monkeypatch):
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

    monkeypatch.setattr(router.ollama, "Client", FakeClient)
    q, tokens = router.extract("Intel R&D 2024")
    s = router.get_settings()
    assert q == {"ticker": "INTC", "metric": "rd_expense", "fiscal_year": 2024}
    assert tokens == Tokens(prompt=11, completion=7)
    assert seen["model"] == s.fast_model and seen["host"] == s.ollama_host
    assert seen["think"] is False and seen["options"]["temperature"] == 0
    props = seen["format"]["properties"]
    assert len(props["ticker"]["enum"]) == 51 and props["ticker"]["enum"][-1] == "NONE"
    assert props["metric"]["enum"] == [*router.load_metric_map()["metrics"], "NONE"]
    assert props["fiscal_year"]["type"] == "integer"
