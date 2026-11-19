"""Graph transitions with a fake planner/LLM, stubbed tools, answerer and verifier."""

from src.agent import graph
from src.agent.fast_path import NOT_FOUND
from src.agent.llm import LLMError
from src.agent.state import MAX_RETRIES, MAX_TOOL_CALLS, Claim, Draft, PlanStep, VerifyResult
from src.api.schemas import AskResponse, Tokens
from src.tools.types import ToolResult
from tests.agent_loop.helpers import SEMIS_FACTS, accn, chunk_result, sql_result

SEMIS_PLAN = [
    PlanStep(tool="sql_query", goal="facts", sector="semiconductors",
             metrics=["rd_expense", "revenue", "gross_profit"], fiscal_years=[2024, 2025]),
    PlanStep(tool="calculate", goal="rd share change", name="rd_share_change",
             expression="rd_expense_2025/revenue_2025 - rd_expense_2024/revenue_2024"),
    PlanStep(tool="calculate", goal="gm change", name="gross_margin_change",
             expression="gross_profit_2025/revenue_2025 - gross_profit_2024/revenue_2024"),
]


class Fake:
    """Records calls; each stub is replaceable per test."""

    def __init__(self, monkeypatch, plan):
        self.plan = plan
        self.sql_calls, self.search_calls, self.answers, self.verifies = [], [], [], []
        self.sql = lambda sql: sql_result(SEMIS_FACTS)
        self.search = lambda **kw: chunk_result(3)
        self.grade_reply = {"relevant_ids": [1], "rewrite": ""}
        self.draft = None          # None: one claim citing the first calc id
        self.verify_fn = None      # None: every claim passes
        monkeypatch.setattr(graph.planner, "plan",
                            lambda q: (list(self.plan), Tokens(prompt=10, completion=5)))
        monkeypatch.setattr(graph.sql_tool, "call",
                            lambda sql: self.sql_calls.append(sql) or self.sql(sql))
        monkeypatch.setattr(graph.search_tool, "call",
                            lambda **kw: self.search_calls.append(kw) or self.search(**kw))
        monkeypatch.setattr(graph.grader, "chat_json",
                            lambda *a, **k: (self.grade_reply, Tokens(prompt=3, completion=1)))
        monkeypatch.setattr(graph.answerer, "answer", self._answer)
        monkeypatch.setattr(graph.verifier, "verify", self._verify)

    def _answer(self, question, tool_results, feedback=None):
        self.answers.append(feedback)
        if self.draft is not None:
            d = self.draft(len(self.answers), tool_results) if callable(self.draft) \
                else self.draft
            return d, Tokens(prompt=100, completion=30)
        ids = [d for r in tool_results if r.ok for d in r.data]
        calc = next((d for d in ids if d["source_id"].startswith("calc:")), None) \
            or next(d for d in ids if d["source_id"].startswith(("xbrl:", "chunk:")))
        return Draft(claims=[Claim(text="NVIDIA's ratio changed.",
                                   source_ids=[calc["source_id"]])]), \
            Tokens(prompt=100, completion=30)

    def _verify(self, draft, tool_results):
        self.verifies.append(draft)
        if self.verify_fn:
            return self.verify_fn(draft)
        return VerifyResult(ok_claims=list(draft.claims))


def names(resp: AskResponse) -> list[str]:
    return [s.name for s in resp.steps]


def flags(resp: AskResponse) -> list[str]:
    return resp.steps[-1].detail["flags"]


def test_semis_flow_and_response_fields(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN)
    resp = graph.run_agent("semis question")
    assert names(resp) == ["plan", "tool_call", "grade", "tool_call", "grade", "tool_call",
                           "grade", "answer", "verify", "flags"]
    assert len(f.sql_calls) == 1 and "accession_no" in f.sql_calls[0]
    calc_steps = [s.detail for s in resp.steps if s.name == "tool_call"
                  and s.detail["tool"] == "calculate"]
    assert [[r["ticker"] for r in c["results"]] for c in calc_steps] == [["NVDA", "INTC"],
                                                                         ["NVDA"]]
    assert calc_steps[1]["notes"] == ["INTC: missing gross_profit_2025"]
    assert resp.steps[1].detail["rows"] == len(SEMIS_FACTS)
    # The claim cites a calc id, which resolves to NVIDIA's filings.
    assert resp.answer.startswith("NVIDIA's ratio changed ")
    assert {c.accession_no for c in resp.citations} == {accn("NVDA", 2024),
                                                        accn("NVDA", 2025)}
    assert resp.tokens == Tokens(prompt=110, completion=35)
    assert isinstance(resp.latency_ms, int) and resp.latency_ms >= 0
    assert flags(resp) == [] and resp.steps[-1].detail["stop_reason"] == "done"
    assert resp.steps[-1].detail["tool_calls"] == 3


def test_tool_cap_gives_partial_answer(monkeypatch):
    plan = [PlanStep(tool="search_filings", goal="g", query=f"q{i}") for i in range(12)]
    f = Fake(monkeypatch, plan)
    resp = graph.run_agent("q")
    assert len(f.search_calls) == MAX_TOOL_CALLS
    assert names(resp).count("tool_call") == MAX_TOOL_CALLS
    assert graph.FLAG_CAP in flags(resp)
    assert resp.steps[-1].detail["stop_reason"] == "tool cap"
    assert resp.answer != NOT_FOUND and resp.citations   # answered from evidence so far


def test_looping_retries_count_toward_cap(monkeypatch):
    plan = [PlanStep(tool="search_filings", goal="g", query=f"q{i}") for i in range(5)]
    f = Fake(monkeypatch, plan)
    n = iter(range(100))
    f.grade_reply = None

    def judge(*a, **k):   # never relevant, always a new rewrite: loops until stopped
        return {"relevant_ids": [], "rewrite": f"rewrite {next(n)}"}, Tokens()
    monkeypatch.setattr(graph.grader, "chat_json", judge)
    resp = graph.run_agent("q")
    assert len(f.search_calls) == MAX_TOOL_CALLS     # 3 per step (1 + 2 retries), capped
    queries = [c["query"] for c in f.search_calls]
    assert queries[:3] == ["q0", "rewrite 0", "rewrite 1"] and queries[3] == "q1"
    assert graph.FLAG_CAP in flags(resp)
    assert resp.answer == NOT_FOUND and resp.citations == []   # nothing relevant kept
    assert f.answers == []                                     # no LLM answer without evidence


def test_grader_retries_at_most_twice(monkeypatch):
    plan = [PlanStep(tool="search_filings", goal="g", query="q")]
    f = Fake(monkeypatch, plan)
    n = iter(range(100))
    monkeypatch.setattr(graph.grader, "chat_json",
                        lambda *a, **k: ({"relevant_ids": [], "rewrite": f"r{next(n)}"},
                                         Tokens()))
    resp = graph.run_agent("q")
    assert len(f.search_calls) == 1 + MAX_RETRIES
    grades = [s.detail for s in resp.steps if s.name == "grade"]
    assert [g["retry"] for g in grades] == [True, True, False]
    assert "retry_skipped" in grades[-1]


def test_transient_error_retried_without_repeat_stop(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    results = iter([ToolResult.fail("database error: timeout"), sql_result(SEMIS_FACTS)])
    f.sql = lambda sql: next(results)
    f.draft = Draft(claims=[Claim(text="x.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])])
    resp = graph.run_agent("q")
    assert len(f.sql_calls) == 2 and flags(resp) == []


def test_validation_error_not_retried(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    f.sql = lambda sql: ToolResult.fail("include accession_no in the SELECT list")
    resp = graph.run_agent("q")
    assert len(f.sql_calls) == 1 and resp.answer == NOT_FOUND


def test_repeated_identical_call_stops_early(monkeypatch):
    step = PlanStep(tool="search_filings", goal="g", query="q")
    other = PlanStep(tool="search_filings", goal="different goal, same call", query="q")
    f = Fake(monkeypatch, [step, other, PlanStep(tool="search_filings", goal="g", query="z")])
    resp = graph.run_agent("q")
    assert len(f.search_calls) == 1
    assert graph.FLAG_REPEAT in flags(resp)
    assert resp.steps[-1].detail["stop_reason"] == "repeated call"
    assert resp.answer != NOT_FOUND     # partial answer from the first call


def test_rewrite_back_to_earlier_query_is_a_repeat(monkeypatch):
    f = Fake(monkeypatch, [PlanStep(tool="search_filings", goal="g", query="a"),
                           PlanStep(tool="search_filings", goal="g", query="b")])
    replies = iter([{"relevant_ids": [1], "rewrite": ""}, {"relevant_ids": [], "rewrite": "a"}])
    monkeypatch.setattr(graph.grader, "chat_json", lambda *a, **k: (next(replies), Tokens()))
    resp = graph.run_agent("q")
    assert [c["query"] for c in f.search_calls] == ["a", "b"]
    assert graph.FLAG_REPEAT in flags(resp)


def test_not_found_when_no_rows(monkeypatch):
    plan = [PlanStep(tool="sql_query", goal="g", tickers=["NVDA"], metrics=["revenue"],
                     fiscal_years=[2030])]
    f = Fake(monkeypatch, plan)
    f.sql = lambda sql: ToolResult(ok=True, data=[], sources=[])
    resp = graph.run_agent("NVIDIA revenue FY2030")
    assert resp.answer == NOT_FOUND and resp.citations == []
    assert f.answers == [] and "fiscal_year IN (2030)" in f.sql_calls[0]
    assert names(resp) == ["plan", "tool_call", "grade", "answer", "flags"]


def test_not_found_when_draft_says_so(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    f.draft = Draft(claims=[Claim(text="x.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])],
                    not_found=True)
    resp = graph.run_agent("q")
    assert resp.answer == NOT_FOUND and resp.citations == [] and f.verifies == []


def test_answer_writer_failure_is_not_found_and_flagged(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])

    def fail(*a, **k):
        raise LLMError("ollama down")
    f.draft = fail
    resp = graph.run_agent("q")
    assert resp.answer == NOT_FOUND
    assert any(x.startswith("answer writer failed") for x in flags(resp))


def test_failed_claim_reanswered_then_removed_and_flagged(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    good = Claim(text="NVIDIA revenue was $60.9 billion.",
                 source_ids=[f"xbrl:{accn('NVDA', 2024)}"])
    bad = Claim(text="NVIDIA revenue was $99 billion.",
                source_ids=[f"xbrl:{accn('NVDA', 2025)}"])
    f.draft = Draft(claims=[good, bad])
    f.verify_fn = lambda d: VerifyResult(
        ok_claims=[c for c in d.claims if c is not bad and c != bad],
        failed_claims=[(c, "99e9 not in source") for c in d.claims if c == bad])
    resp = graph.run_agent("q")
    assert len(f.answers) == 2
    assert f.answers[0] is None and "NVIDIA revenue was $99 billion." in f.answers[1]
    assert "99e9 not in source" in f.answers[1]
    assert names(resp).count("verify") == 2 and names(resp).count("answer") == 2
    assert flags(resp) == ["removed unverified claim: NVIDIA revenue was $99 billion."]
    assert resp.answer == "NVIDIA revenue was $60.9 billion [1]."
    assert [c.accession_no for c in resp.citations] == [accn("NVDA", 2024)]


def test_reanswer_fixes_claim(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    bad = Claim(text="Wrong $1.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])
    good = Claim(text="Right.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])
    f.draft = lambda n, tr: Draft(claims=[bad] if n == 1 else [good])
    f.verify_fn = lambda d: VerifyResult(
        ok_claims=[c for c in d.claims if c != bad],
        failed_claims=[(c, "1 not in source") for c in d.claims if c == bad])
    resp = graph.run_agent("q")
    assert len(f.answers) == 2 and flags(resp) == []
    assert resp.answer == "Right [1]."


def test_all_claims_removed_is_not_found(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    bad = Claim(text="Wrong $1.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])
    f.draft = Draft(claims=[bad])
    f.verify_fn = lambda d: VerifyResult(failed_claims=[(c, "no") for c in d.claims])
    resp = graph.run_agent("q")
    assert resp.answer == NOT_FOUND and resp.citations == []
    assert flags(resp) == ["removed unverified claim: Wrong $1."]


def test_reanswer_not_found_does_not_loop(monkeypatch):
    f = Fake(monkeypatch, SEMIS_PLAN[:1])
    bad = Claim(text="Wrong $1.", source_ids=[f"xbrl:{accn('NVDA', 2024)}"])
    f.draft = lambda n, tr: Draft(claims=[bad]) if n == 1 else Draft(not_found=True)
    f.verify_fn = lambda d: VerifyResult(failed_claims=[(c, "no") for c in d.claims])
    resp = graph.run_agent("q")
    assert len(f.answers) == 2 and resp.answer == NOT_FOUND


def test_bad_llm_args_never_raise(monkeypatch):
    bad = PlanStep.model_construct(tool="sql_query", goal="g", tickers=["NVDA"], sector=None,
                                   metrics=["revenue"], fiscal_years=[2024.0], query=None,
                                   item=None, expression=None, name=None)
    f = Fake(monkeypatch, [bad])
    resp = graph.run_agent("q")
    assert f.sql_calls == [] and resp.answer == NOT_FOUND
    assert resp.steps[1].detail["ok"] is False


def test_search_grading_filters_evidence(monkeypatch):
    f = Fake(monkeypatch, [PlanStep(tool="search_filings", goal="g", query="q")])
    f.grade_reply = {"relevant_ids": [2], "rewrite": ""}
    seen = []
    f.draft = lambda n, tr: (seen.append([d["source_id"] for r in tr for d in r.data])
                             or Draft(claims=[Claim(text="Said so.",
                                                    source_ids=["chunk:AMD-2"])]))
    resp = graph.run_agent("q")
    assert seen == [["chunk:AMD-2"]]
    assert resp.steps[1].detail["chunks"] == 3 and resp.steps[2].detail["kept"] == 1
    assert resp.answer == "Said so [1]."


def test_empty_plan_goes_to_answer(monkeypatch):
    f = Fake(monkeypatch, [])
    resp = graph.run_agent("q")
    assert resp.answer == NOT_FOUND and f.sql_calls == f.search_calls == []
