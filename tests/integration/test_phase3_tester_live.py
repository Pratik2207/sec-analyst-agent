"""Phase 3 tester: live checks against the real pilot data (read-only).

Real Postgres (agent_reader), the real `filings` Qdrant collection (search only), the real
parsed sections, and Ollama for the router (5 calls) and the baseline (1 call).
"""

import json
import statistics
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.agent import router
from src.api.main import app
from src.api.schemas import AskResponse
from src.baseline import naive_rag
from src.tools import calculator, companies_tool, search_tool, section_tool, sql_tool
from src.tools.types import ToolResult

pytestmark = pytest.mark.integration

DATA = Path(__file__).resolve().parents[2] / "data"
INTEL = "What was Intel's R&D in FY2024?"
SEMIS = ("Which semiconductor companies raised R&D as a share of revenue while gross margin "
         "fell, FY2024 to FY2025?")


def check_invariant(res: ToolResult) -> None:
    """AC1: JSON output, every item's source_id resolves to exactly one Source, and every
    filing source becomes a Citation with an https://www.sec.gov/ url."""
    assert res.ok, res.error
    assert res.data
    json.loads(res.model_dump_json())
    ids = [s.source_id for s in res.sources]
    for d in res.data:
        assert ids.count(d["source_id"]) == 1, (d["source_id"], ids)
    for s in res.sources:
        if s.kind in ("xbrl", "chunk", "section"):
            c = s.citation()
            assert c is not None and c.url.startswith("https://www.sec.gov/"), s
            assert c.ticker and c.fiscal_year and c.accession_no and c.form == "10-K"
        else:
            assert s.citation() is None


# ---- AC1: every tool, real calls ------------------------------------------------------------

def test_live_sql_tool_invariant():
    res = sql_tool.call("SELECT ticker, fiscal_year, metric, value, accession_no "
                        "FROM financial_facts WHERE metric = 'revenue' ORDER BY ticker")
    check_invariant(res)
    assert len({s.source_id for s in res.sources}) == len(res.sources)
    assert all(s.kind == "xbrl" for s in res.sources)


def test_live_sql_tool_companies_rows_invariant():
    check_invariant(sql_tool.call("SELECT ticker, name FROM companies"))


def test_live_sql_tool_truncated_result_invariant():
    # > 200 rows, all of them cited facts: the truncation note must still resolve (AC1).
    res = sql_tool.call("SELECT a.ticker, a.accession_no FROM financial_facts a "
                        "CROSS JOIN financial_facts b")
    check_invariant(res)


def test_live_companies_tool_invariant():
    res = companies_tool.call()
    check_invariant(res)
    semis = companies_tool.call("semiconductors")
    check_invariant(semis)
    assert {d["ticker"] for d in semis.data} >= {"NVDA", "INTC"}
    assert all(d["sector"] == "semiconductors" for d in semis.data)


def test_live_search_tool_invariant():
    res = search_tool.call("gross margin drivers", sector="semiconductors", fiscal_year=2025,
                           k=4)
    check_invariant(res)
    assert all(s.kind == "chunk" for s in res.sources)


@pytest.mark.skipif(not (DATA / "processed" / "sections").exists(), reason="no sections")
def test_live_section_tool_invariant():
    res = section_tool.call("nvda", "2025", "7", max_tokens=300)
    check_invariant(res)


def test_calculator_invariant():
    res = calculator.call("(rd / revenue) * 100", {"rd": 1, "revenue": 4})
    check_invariant(res)
    assert res.data[0]["result"] == 25.0
    assert res.data[0]["expression"] == "(rd / revenue) * 100"


# ---- AC3 + NFR-4: router and /ask on the named questions, fast-path latency -----------------

@pytest.fixture(scope="module")
def client():
    try:
        httpx.get(get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")
    return TestClient(app)


@pytest.fixture(scope="module")
def ask_bodies(client):
    """5 sequential /ask calls on the Intel question (5 router LLM calls)."""
    mp = pytest.MonkeyPatch()
    mp.setattr(router, "KEEP_ALIVE", "1m")
    bodies, wall = [], []
    try:
        for _ in range(5):
            t = time.perf_counter()
            r = client.post("/ask", json={"question": INTEL})
            wall.append(time.perf_counter() - t)
            assert r.status_code == 200
            bodies.append(r.json())
    finally:
        mp.undo()
    return bodies, wall


def test_intel_question_takes_fast_path(ask_bodies):
    for body in ask_bodies[0]:
        AskResponse.model_validate(body)
        assert [s["name"] for s in body["steps"]] == ["route", "sql_query"]
        assert body["steps"][0]["detail"]["kind"] == "fast"
        assert "$16.55 billion" in body["answer"]
        [c] = body["citations"]
        assert c["ticker"] == "INTC" and c["fiscal_year"] == 2024
        assert c["url"].startswith("https://www.sec.gov/")


def test_fast_path_latency_p50_under_5s(ask_bodies):
    bodies, wall = ask_bodies
    server = [b["latency_ms"] for b in bodies]
    p50 = statistics.median(server)
    print(f"\nfast-path latency_ms per run {server}; wall s "
          f"{[round(w, 2) for w in wall]}; p50 {p50} ms; p50 warm (runs 2-5) "
          f"{statistics.median(server[1:])} ms")
    assert p50 < 5000


def test_semis_question_routes_to_agent(client):
    body = client.post("/ask", json={"question": SEMIS}).json()
    AskResponse.model_validate(body)
    assert body["steps"][0]["detail"]["kind"] == "agent"
    # Phase 4: the agent now answers (Phase 3 asserted the placeholder had no citations)


# ---- AC4: live baseline answer has the /ask shape (1 LLM call, ~40 s) ----------------------

def test_live_baseline_shape_matches_ask(client, ask_bodies):
    base = naive_rag.answer("What drove NVIDIA's data center revenue growth in fiscal 2025?")
    assert isinstance(base, AskResponse)
    base_json = json.loads(base.model_dump_json())
    ask_json = ask_bodies[0][0]
    assert set(base_json) == set(ask_json)
    assert set(base_json["tokens"]) == set(ask_json["tokens"])
    for c in base_json["citations"]:
        assert set(c) == set(ask_json["citations"][0])
        assert c["url"].startswith("https://www.sec.gov/")
    print(f"\nbaseline latency_ms {base.latency_ms}, citations {len(base.citations)}, "
          f"answer {base.answer[:200]!r}")
