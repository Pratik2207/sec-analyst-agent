"""Phase 5 tester: scorer edge cases, NFR logic and report rendering on synthetic scores,
the ablation switches, and settings_override."""

import pytest

from config.settings import get_settings
from evals import systems as sysmod
from evals.schema import DatasetItem, GoldSource, RunResult
from evals.scoring import report
from evals.scoring.citations import citation_score
from evals.scoring.latency import percentile, summarize
from evals.scoring.numbers import number_correct
from evals.scoring.recall import first_hit_rank, is_hit
from evals.scoring.refusal import is_refusal
from src.agent import fast_path, graph, planner, router
from src.agent.state import PlanStep
from src.api.schemas import AskResponse, Citation, Tokens
from src.retrieval.types import SearchHit
from src.tools import search_tool, sql_tool
from src.tools.types import ToolResult

# ---- numbers: scale and sign -------------------------------------------------------------


@pytest.mark.parametrize("answer", [
    "Intel posted a net loss of $18.76 billion.",
    "Net income was -$18,756 million.",
    "Net income: (18,756) (in millions)",
    "Net income was $(18.8) billion.",          # 0.2% off
    "Net income was −18.76 billion dollars.",   # unicode minus
])
def test_negative_usd_any_scale(answer):
    assert number_correct(answer, -18_756_000_000.0, "USD")


def test_trillion_scale_and_wrong_scale():
    assert number_correct("JPM total assets were $3,875,393 million.", 3_875_393e6, "USD")
    assert not number_correct("Total assets were $3.9 million.", 3_875_393e6, "USD")


def test_percent_is_not_scaled_and_wrong_direction_fails():
    assert not number_correct("Growth was 0.9101.", 91.01, "%")
    assert number_correct("Revenue grew 91.0%.", 91.01, "%")
    # Phase 5 code review: the old leniency (magnitude only) is gone for negative golds
    assert not number_correct("Net income grew 45.37%.", -45.37, "%")
    assert number_correct("Net income declined 45.37%.", -45.37, "%")
    assert number_correct("Net income changed by -45.37%.", -45.37, "%")


def test_year_and_date_are_not_numbers_for_matching():
    assert not number_correct("In FY2024 (ended 2024-12-28) results improved.", 2_024e6, "USD")


def test_zero_gold():
    assert number_correct("The change was 0.0 pp.", 0.0, "pp")
    assert not number_correct("The change was 0.1 pp.", 0.0, "pp")


# ---- refusal false positives / negatives ------------------------------------------------

@pytest.mark.parametrize("answer", [
    "Intel's FY2024 net income was -$18.76 billion. Segment detail is not disclosed.",
    "NVIDIA's revenue grew 114.2% to $130.50 billion [1].",
    "Revenue in the U.S. was $10 billion. Other data was not found.",
    "Merck's net income rose by $16.75 billion because FY2024 did not include the large "
    "acquired IPR&D charge.",
    "JPMorgan had the highest net income ($57.05 billion); Goldman does not report R&D.",
])
def test_answers_with_values_are_not_refusals(answer):
    assert not is_refusal(answer)


@pytest.mark.parametrize("answer", [
    "   ", None, "NOT FOUND IN THE FILINGS.",
    "I cannot determine Apple's revenue from the filings available.",
    "There is insufficient information to answer.",
])
def test_refusals_detected(answer):
    assert is_refusal(answer)


# ---- recall -----------------------------------------------------------------------------

def _it(**kw):
    base = {"id": "txt-001", "type": "text", "question": "q", "gold_answer": "a",
            "gold_sources": [GoldSource(ticker="NVDA", fiscal_year=2025, item="7")],
            "gold_contains": ["Data Center", "gross margin"]}
    return DatasetItem(**{**base, **kw})


def _p(text="Gross   margin\nrose on data center mix", ticker="nvda", fy="2025", item="7"):
    return {"text": text, "ticker": ticker, "fiscal_year": fy, "item": item}


def test_recall_matching_rules():
    it = _it()
    assert is_hit(_p(), it)                                    # case/space/str-year tolerant
    assert not is_hit(_p(item="1A"), it)
    assert not is_hit(_p(fy=2024), it)
    assert not is_hit(_p(text="gross margin only"), it)
    assert is_hit(_p(item="1A"), _it(gold_sources=[GoldSource(ticker="NVDA", fiscal_year=2025)]))
    assert is_hit(_p(ticker="AMD"), _it(gold_sources=[
        GoldSource(ticker="NVDA", fiscal_year=2025, item="7"),
        GoldSource(ticker="AMD", fiscal_year=2025, item="7")]))


def test_first_hit_rank_respects_k():
    miss = _p(text="nothing")
    assert first_hit_rank([miss] * 3 + [_p()], _it()) == 4
    assert first_hit_rank([miss] * 10 + [_p()], _it()) is None
    assert first_hit_rank([], _it()) is None


def test_recall_scores_only_counts_items_with_gold_contains():
    items = [_it(), _it(id="txt-002", gold_contains=[])]
    out = report.recall_scores(items, {"full": {"txt-001": [_p()], "txt-002": []},
                                       "no_headers": None})
    assert out["full"]["n"] == 1 and out["full"]["recall"] == 1.0
    assert out["no_headers"]["recall"] is None


# ---- citations --------------------------------------------------------------------------

def _c(t, y):
    return Citation(ticker=t, form="10-K", fiscal_year=y, section="Item 8", accession_no="a",
                    url="u")


def test_citation_accuracy():
    it = _it(gold_sources=[GoldSource(ticker="AMD", fiscal_year=2023),
                           GoldSource(ticker="AMD", fiscal_year=2024)])
    assert citation_score([_c("amd", 2023), _c("AMD", 2024), _c("AMD", 2022),
                           _c("INTC", 2024)], it) == 0.5
    assert citation_score([], it) is None
    assert citation_score([_c("AMD", 2023)], _it(gold_sources=[])) is None


# ---- percentiles ------------------------------------------------------------------------

def test_percentiles_match_numpy_linear():
    vals = [10, 1, 7, 3, 5]
    assert percentile(vals, 50) == 5
    assert percentile(vals, 95) == pytest.approx(9.4)   # numpy.percentile(vals, 95)
    assert percentile(vals, 0) == 1 and percentile(vals, 100) == 10
    assert percentile([4.2], 95) == 4.2 and percentile([], 50) is None
    assert summarize([], [])["p50_s"] is None


# ---- score_result / NFR / report on synthetic scores ------------------------------------

def _resp(answer, cits=()):
    return AskResponse(answer=answer, citations=list(cits), steps=[],
                       tokens=Tokens(prompt=10, completion=5), latency_ms=1)


def _rr(system, qid, answer, wall=1.0, route="agent", error=None):
    return RunResult(qid=qid, system=system, response=None if error else _resp(answer),
                     route=route, wall_s=wall, error=error)


def test_score_result_multihop_signed_and_refusal():
    it = DatasetItem(id="mh-001", type="multihop", question="q", gold_answer="g",
                     gold_value=-4.2, unit="pp",
                     gold_sources=[GoldSource(ticker="QCOM", fiscal_year=2025)])
    row = report.score_result(it, _rr("agent", "mh-001", "It fell 4.20 pp."),
                              {"correctness": {"score": 1.0, "reason": "ok"}})
    assert row["numeric_match"] is True and row["score"] == 1.0
    row = report.score_result(it, _rr("agent", "mh-001", "Not found in the filings."),
                              {"correctness": {"score": 1.0}})
    assert row["score"] == 0.0 and row["numeric_match"] is False


def _agg(acc_overall, mh_agent, mh_base, faith=0.96, mh_p50=30, mh_p95=90):
    return {"agent": {"overall": {"accuracy": acc_overall, "faithfulness": faith},
                      "multihop": {"accuracy": mh_agent, "p50_s": mh_p50, "p95_s": mh_p95}},
            "baseline": {"multihop": {"accuracy": mh_base}}}


def _status(nfrs):
    return {n["id"]: n["status"] for n in nfrs}


def test_nfr_boundaries_are_inclusive_where_the_prd_says_ge():
    rows = [{"system": "agent", "route": "fast", "error": None, "wall_s": 4.99}]
    s = _status(report.nfr_check(_agg(0.80, 25 / 30, 17.5 / 30, faith=0.95),
                                 {"full": {"recall": 0.85}}, rows))
    assert s == {"NFR-1": "PASS", "NFR-2": "PASS", "NFR-3": "PASS", "NFR-4": "PASS",
                 "NFR-5": "PASS"}


def test_nfr_strict_latency_bounds_and_fails():
    rows = [{"system": "agent", "route": "fast", "error": None, "wall_s": 5.0},
            {"system": "baseline", "route": "fast", "error": None, "wall_s": 0.1},
            {"system": "agent", "route": "fast", "error": "boom", "wall_s": 0.1}]
    s = _status(report.nfr_check(_agg(0.9, 0.7, 0.5, faith=0.9, mh_p50=60, mh_p95=100),
                                 {"full": {"recall": 0.84}}, rows))
    assert s == {"NFR-1": "FAIL", "NFR-2": "FAIL", "NFR-3": "FAIL", "NFR-4": "FAIL",
                 "NFR-5": "FAIL"}


def test_nfr_na_when_unmeasured():
    s = _status(report.nfr_check({}, {}, []))
    assert set(s.values()) == {"N/A"}


def test_report_renders_per_type_tables_nfrs_and_escapes_pipes():
    items = [DatasetItem(id="num-001", type="number", question="Rev | AMD?", gold_answer="g",
                         gold_value=100.0, unit="USD",
                         gold_sources=[GoldSource(ticker="AMD", fiscal_year=2023)]),
             DatasetItem(id="na-001", type="unanswerable", question="Apple?", gold_answer="nf")]
    by_id = {it.id: it for it in items}
    runs = [(items[0], _rr("agent", "num-001", "It was $90.", route="fast")),
            (items[1], _rr("agent", "na-001", "Not found in the filings.")),
            (items[0], _rr("baseline", "num-001", "It was $100.")),
            (items[1], _rr("baseline", "na-001", "Apple made $5.")),
            (items[0], _rr("agent:no_sql", "num-001", "x", error="boom"))]
    rows = [report.score_result(it, rr, None) for it, rr in runs]
    agg = report.aggregate(rows)
    assert agg["agent"]["number"]["accuracy"] == 0.0
    assert agg["baseline"]["overall"]["accuracy"] == 0.5
    assert agg["agent"]["unanswerable"]["refusal_accuracy"] == 1.0
    assert agg["agent:no_sql"]["overall"]["errors"] == 1
    recall = report.recall_scores(items, {"full": {}, "no_headers": None})
    nfrs = report.nfr_check(agg, recall, rows)
    fails = report.failures(rows, by_id, recall)
    assert [f["cause"] for f in fails] == ["wrong number"]
    meta = {"run_id": "t", "date": "d", "dataset": "x", "n_items": 2,
            "counts": {"number": 1, "unanswerable": 1}}
    md = report.render(meta, agg, recall, nfrs, fails)
    for typ in ("number", "unanswerable", "overall"):
        assert f"| {typ} | agent |" in md and f"| {typ} | baseline |" in md
    assert "| agent:no_sql | number |" in md
    for n in ("NFR-1", "NFR-2", "NFR-3", "NFR-4", "NFR-5"):
        assert f"| {n} |" in md
    assert "Rev \\| AMD?" in md
    assert "| no_headers | n/a | n/a | n/a |" in md


# ---- ablation switches ------------------------------------------------------------------

def test_settings_override_restores_on_exception():
    s = get_settings()
    before = (s.search_use_reranker, list(s.agent_disabled_tools))
    with pytest.raises(RuntimeError):
        with sysmod.settings_override(search_use_reranker=False,
                                      agent_disabled_tools=["sql_query"]):
            assert get_settings().search_use_reranker is False
            raise RuntimeError("x")
    assert (s.search_use_reranker, list(s.agent_disabled_tools)) == before


def test_search_tool_honours_settings(monkeypatch):
    seen = []

    def fake(query, filters=None, k=8, use_reranker=True, use_sparse=True, **kw):
        seen.append((use_reranker, use_sparse))
        return []

    monkeypatch.setattr(search_tool, "hybrid_search", fake)
    search_tool.call("gross margin")
    with sysmod.settings_override(search_use_reranker=False, search_use_sparse=False):
        search_tool.call("gross margin")
    with sysmod.settings_override(search_use_sparse=False):
        search_tool.call("gross margin")
    assert seen == [(True, True), (False, False), (True, False)]


SQL_RAW = {"action": "sql_query", "about": "fetch", "tickers": ["AMD"],
           "metrics": ["revenue"], "fiscal_years": [2024]}


def test_planner_drops_disabled_sql_and_falls_back(monkeypatch):
    assert [s.tool for s in planner.normalise([SQL_RAW])] == ["sql_query"]
    monkeypatch.setattr(planner, "chat_json",
                        lambda *a, **k: ({"steps": [SQL_RAW]}, Tokens()))
    with sysmod.settings_override(agent_disabled_tools=["sql_query"]):
        assert planner.normalise([SQL_RAW]) == []
        steps, _ = planner.plan("AMD revenue 2024?")
    assert [s.tool for s in steps] == ["search_filings"]


def test_dispatch_refuses_disabled_sql(monkeypatch):
    calls = []
    monkeypatch.setattr(sql_tool, "call", lambda sql: calls.append(sql) or ToolResult(
        ok=True, data=[], sources=[]))
    step = PlanStep(tool="sql_query", goal="g", tickers=["AMD"], metrics=["revenue"],
                    fiscal_years=[2024])
    with sysmod.settings_override(agent_disabled_tools=["sql_query"]):
        res, _ = graph.dispatch(step, [])
    assert not res.ok and "disabled" in res.error and calls == []
    res, _ = graph.dispatch(step, [])
    assert calls   # enabled again after the override


def test_no_sql_ablation_makes_no_sql_call_on_fast_route(monkeypatch):
    """X-6 'without the SQL tool': the agent:no_sql ablation runs number questions, which the
    router sends to the fast path. The fast path must not query SQL under the ablation."""
    calls = []
    monkeypatch.setattr(router, "route", lambda q: router.Route(
        kind="fast", query=router.FactQuery(ticker="AMD", metric="revenue", fiscal_year=2023)))
    monkeypatch.setattr(sql_tool, "call", lambda sql: calls.append(sql) or ToolResult(
        ok=True, data=[], sources=[]))
    base, overrides, _ = sysmod.END_TO_END_ABLATIONS["agent:no_sql"]
    with sysmod.settings_override(**overrides):
        rr = sysmod.SYSTEMS[base]("What was AMD's revenue in 2023?")
    assert calls == [], f"SQL ran under agent:no_sql (route={rr.route})"


def test_baseline_system_returns_contexts(monkeypatch):
    from src.baseline import naive_rag
    hit = SearchHit(id="p", score=1.0, payload={"text": "ctx"})
    monkeypatch.setattr(naive_rag, "answer_traced", lambda q: (_resp("a"), [hit]))
    rr = sysmod.baseline_system("q")
    assert rr.contexts == ["ctx"] and rr.error is None
    monkeypatch.setattr(naive_rag, "answer_traced",
                        lambda q: (_ for _ in ()).throw(ValueError("x")))
    assert sysmod.baseline_system("q").error.startswith("ValueError")


def test_fast_path_answer_still_works_unchanged():
    assert fast_path.format_usd(-18_756_000_000) == "-$18.76 billion"
