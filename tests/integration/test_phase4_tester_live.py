"""Phase 4 tester, live: the real dispatcher on the real database (agent_reader), then a
few /ask questions end to end with Ollama (sequential, at most 5 LLM questions).

Run with -s to see latencies and answers."""

import re
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.agent import graph
from src.agent.fast_path import NOT_FOUND
from src.agent.state import PlanStep
from src.api.main import app
from src.api.schemas import AskResponse
from src.tools import calculator, sql_tool

pytestmark = pytest.mark.integration

SEMIS = ("Which semiconductor companies raised R&D as a share of revenue while gross margin "
         "fell, FY2024 to FY2025?")
SEMIS_TICKERS = ("NVDA", "AMD", "INTC", "QCOM")


def _facts() -> dict[str, dict[str, float]]:
    res = sql_tool.call("SELECT f.ticker, f.fiscal_year, f.metric, f.value, f.accession_no "
                        "FROM financial_facts f WHERE f.metric IN "
                        "('rd_expense', 'revenue', 'gross_profit', 'net_income') "
                        "AND f.fiscal_year IN (2023, 2024, 2025)")
    assert res.ok, res.error
    out: dict[str, dict[str, float]] = {}
    for d in res.data:
        out.setdefault(d["ticker"], {})[f"{d['metric']}_{d['fiscal_year']}"] = d["value"]
    return out


# ---- real dispatcher, no LLM ----------------------------------------------------------

def test_dispatch_bank_rd_returns_no_rows():
    step = PlanStep(tool="sql_query", goal="g", tickers=["JPM"], metrics=["rd_expense"],
                    fiscal_years=[2024])
    res, extra = graph.dispatch(step, [])
    assert res.ok and res.data == [], res.error
    assert "accession_no" in extra["sql"]


def test_dispatch_semis_calcs_match_db():
    truth = _facts()
    sql = PlanStep(tool="sql_query", goal="g", sector="semiconductors",
                   metrics=["rd_expense", "revenue", "gross_profit"], fiscal_years=[2024, 2025])
    calc = PlanStep(tool="calculate", goal="g", name="rd_share_change",
                    expression="rd_expense_2025/revenue_2025 - rd_expense_2024/revenue_2024")
    r1, _ = graph.dispatch(sql, [])
    assert r1.ok and {d["ticker"] for d in r1.data} >= set(SEMIS_TICKERS)
    r2, notes = graph.dispatch(calc, [r1])
    assert r2.ok, (r2.error, notes)
    for d in r2.data:
        f = truth[d["ticker"]]
        want = f["rd_expense_2025"] / f["revenue_2025"] - f["rd_expense_2024"] / f["revenue_2024"]
        assert d["result"] == pytest.approx(want, rel=1e-9)
        assert all(s.startswith("xbrl:") for s in d["input_source_ids"])


# ---- live /ask (Ollama) ---------------------------------------------------------------

_CACHE: dict[str, tuple[dict, float]] = {}


@pytest.fixture(scope="module")
def client():
    try:
        httpx.get(get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")
    return TestClient(app)


def ask(client, q: str) -> dict:
    if q not in _CACHE:
        t = time.perf_counter()
        r = client.post("/ask", json={"question": q})
        assert r.status_code == 200, r.text
        _CACHE[q] = (r.json(), time.perf_counter() - t)
        body = r.json()
        flags = body["steps"][-1]["detail"].get("flags") if body["steps"] else None
        tools = [s["detail"].get("tool") for s in body["steps"] if s["name"] == "tool_call"]
        print(f"\n[{_CACHE[q][1]:.1f}s] {q}\n  route={body['steps'][0]['detail']}"
              f"\n  answer={body['answer']}\n  flags={flags}\n  tools={tools}")
    return _CACHE[q][0]


def _check_types_and_citations(body: dict) -> None:
    AskResponse.model_validate(body)                       # FR-14: the Pydantic model
    assert isinstance(body["answer"], str) and body["answer"]
    assert isinstance(body["latency_ms"], int) and body["latency_ms"] > 0
    assert isinstance(body["tokens"]["prompt"], int)
    assert isinstance(body["tokens"]["completion"], int)
    assert all(isinstance(s["name"], str) and isinstance(s["detail"], dict)
               for s in body["steps"])
    for c in body["citations"]:
        assert c["form"] == "10-K" and c["url"].startswith("https://www.sec.gov/")
        assert c["ticker"] and isinstance(c["fiscal_year"], int) and c["accession_no"]
    if body["answer"] != NOT_FOUND:                        # AC5: each sentence cited
        n = len(body["citations"])
        for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", body["answer"]):
            marks = [int(m) for m in re.findall(r"\[(\d+)\]", s)]
            assert marks and all(1 <= m <= n for m in marks), s


def test_live_semis_multihop(client):
    body = ask(client, SEMIS)
    _check_types_and_citations(body)
    assert body["citations"], body["answer"]
    assert re.search(r"\b(none|no (semiconductor )?compan|neither|did not|didn't)\b",
                     body["answer"], re.I), body["answer"]
    for t in SEMIS_TICKERS:   # no company is named as qualifying
        assert not re.search(rf"\b{t}\b[^.]*\b(qualif|meets?|satisf)", body["answer"]), t
    calls = [s["detail"] for s in body["steps"] if s["name"] == "tool_call"]
    calcs = [c for c in calls if c["tool"] == "calculate"]
    assert calcs, "ratios must come from calculate steps"         # AC1 / FR-7
    plan = next(s for s in body["steps"] if s["name"] == "plan")
    assert len(plan["detail"]["steps"]) >= 2
    truth = _facts()
    for c in calcs:   # each computed change has the sign the database gives
        expr = c["args"]["expression"]
        for r in c["results"]:
            f = truth[r["ticker"]]
            names = set(re.findall(r"[a-z_]+_\d{4}", expr))
            want = calculator.call(expr, {k: f[k] for k in names}).data[0]["result"]
            assert r["result"] == pytest.approx(want, rel=1e-9), (r, expr)


def test_live_text_question(client):
    body = ask(client, "What supply chain risks does NVIDIA describe in its FY2025 10-K?")
    _check_types_and_citations(body)
    assert body["answer"] != NOT_FOUND and body["citations"]
    assert all(c["ticker"] == "NVDA" for c in body["citations"])
    assert any(not c["section"].startswith("Item 8") for c in body["citations"])


def test_live_bank_rd_not_found(client):
    body = ask(client, "Compare JPMorgan's and Goldman Sachs's R&D expense in FY2024.")
    _check_types_and_citations(body)
    assert body["answer"] == NOT_FOUND, body["answer"]
    assert body["citations"] == []


def test_live_unknown_company_not_found(client):
    body = ask(client, "How did Acme Robotics' revenue change from FY2024 to FY2025?")
    _check_types_and_citations(body)
    assert body["answer"] == NOT_FOUND, body["answer"]


def test_live_flag_path_invariants(client):
    """A question that tends to stress the verifier (many numbers, several companies).
    Whatever happens, removed claims must not be in the answer and stops must be flagged."""
    body = ask(client, "For each pharma company, give FY2023, FY2024 and FY2025 revenue and "
                       "net income, and the percent change in each from FY2023 to FY2025.")
    _check_types_and_citations(body)
    final = body["steps"][-1]["detail"]
    for fl in final["flags"]:
        if fl.startswith("removed unverified claim: "):
            assert fl.removeprefix("removed unverified claim: ").rstrip(".") not in body["answer"]
    if final["stop_reason"] == "tool cap":
        assert graph.FLAG_CAP in final["flags"]
    if final["stop_reason"] == "repeated call":
        assert graph.FLAG_REPEAT in final["flags"]
    assert final["tool_calls"] <= 8
