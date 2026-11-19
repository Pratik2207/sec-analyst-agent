"""run_eval with stub systems, a stub retriever and a stubbed chat_json (no Postgres,
Qdrant or Ollama)."""

import json

import pytest

from config.settings import get_settings
from evals import run_eval
from evals import systems as sysmod
from evals.schema import RunResult
from evals.scoring import report
from src.agent import llm
from src.api.schemas import AskResponse, Citation, Tokens

ITEMS = [
    {"id": "num-1", "type": "number", "question": "Intel R&D FY2024?",
     "gold_answer": "$16.55 billion", "gold_value": 16546000000.0, "unit": "USD",
     "gold_sources": [{"ticker": "INTC", "fiscal_year": 2024, "item": "8"}]},
    {"id": "txt-1", "type": "text", "question": "Why did NVIDIA gross margin change?",
     "gold_answer": "Data Center mix.", "gold_contains": ["gross margin"],
     "gold_sources": [{"ticker": "NVDA", "fiscal_year": 2025, "item": "7"}]},
    {"id": "mh-1", "type": "multihop", "question": "Which semis raised R&D share?",
     "gold_answer": "None; AMD R&D share fell 5.0 pp.", "gold_value": -5.0, "unit": "pp",
     "gold_sources": [{"ticker": "AMD", "fiscal_year": 2025, "item": "8"}]},
    {"id": "na-1", "type": "unanswerable", "question": "NVIDIA revenue FY2030?",
     "gold_answer": "Not found in the filings."},
]

ANSWERS = {
    "Intel R&D FY2024?": ("Intel's R&D was $16.55 billion.", "fast", "INTC", 2024),
    "Why did NVIDIA gross margin change?": ("Higher Data Center mix.", "agent", "NVDA", 2025),
    "Which semis raised R&D share?": ("None; AMD's R&D share fell 5.0 pp.", "agent", "AMD",
                                      2025),
    "NVIDIA revenue FY2030?": ("Not found in the filings.", "agent", None, None),
}


def _response(answer, ticker, fy):
    cits = [Citation(ticker=ticker, form="10-K", fiscal_year=fy, section="Item 7",
                     accession_no="a", url="u")] if ticker else []
    return AskResponse(answer=answer, citations=cits, steps=[],
                       tokens=Tokens(prompt=100, completion=20), latency_ms=1000)


class Env:
    def __init__(self):
        self.calls = []          # (system, question, disabled tools at call time)
        self.fail = set()        # questions that error
        self.retrieve_calls = []
        self.noheader_built = 0
        self.llm_calls = []


@pytest.fixture
def env(tmp_path, monkeypatch):
    e = Env()

    def make(system):
        def fn(question):
            e.calls.append((system, question, list(get_settings().agent_disabled_tools)))
            if question in e.fail:
                return RunResult(qid="", system=system, error="RuntimeError: boom", wall_s=1)
            ans, route, ticker, fy = ANSWERS[question]
            return RunResult(qid="", system=system, response=_response(ans, ticker, fy),
                             contexts=["ctx " + ans], route=route if system == "agent"
                             else None, wall_s=2.0 if route == "fast" else 30.0)
        return fn

    def retrieve(question, config):
        e.retrieve_calls.append((question, config))
        hit = {"ticker": "NVDA", "fiscal_year": 2025, "item": "7",
               "text": "Gross margin increased."}
        miss = {"ticker": "AMD", "fiscal_year": 2025, "item": "7", "text": "x"}
        return [hit if config != "no_sparse" else miss] + [miss] * 9

    def ensure():
        e.noheader_built += 1
        return 123

    def chat_json(model, system, user, schema, think=False):
        e.llm_calls.append(model)
        if "verdict" in schema["properties"]:
            return {"reason": "ok", "verdict": "correct"}, Tokens(prompt=1, completion=1)
        return {"claims": [{"claim": "c", "supported": True}]}, Tokens()

    monkeypatch.setattr(sysmod, "SYSTEMS", {"agent": make("agent"),
                                            "baseline": make("baseline")})
    monkeypatch.setattr(sysmod, "retrieve", retrieve)
    monkeypatch.setattr(sysmod, "ensure_noheader_collection", ensure)
    monkeypatch.setattr(llm, "chat_json", chat_json)
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path / "results")
    ds = tmp_path / "ds.jsonl"
    ds.write_text("\n".join(json.dumps(i) for i in ITEMS), encoding="utf-8")
    e.ds, e.out = ds, tmp_path / "results" / "r1"
    e.run = lambda *args: run_eval.main(["--run-id", "r1", "--dataset", str(ds), *args])
    return e


def test_full_run_writes_caches_and_report(env):
    assert env.run("--skip-noheader") == 0
    raw = env.out / "raw"
    assert (raw / "agent" / "num-1.json").exists()
    assert (raw / "agent_no_sql" / "mh-1.json").exists()
    assert not (raw / "agent_no_sql" / "txt-1.json").exists()    # no_sql: number+multihop
    rr = RunResult.model_validate_json((raw / "agent_no_sql" / "num-1.json").read_text())
    assert rr.qid == "num-1" and rr.system == "agent:no_sql"
    assert (raw / "judge" / "agent" / "txt-1.json").exists()
    assert len(env.calls) == 4 + 4 + 2
    scores = json.loads((env.out / "scores.json").read_text(encoding="utf-8"))
    assert scores["summary"]["agent"]["overall"]["accuracy"] == 1.0
    assert scores["recall"]["full"]["recall"] == 1.0
    assert scores["recall"]["no_sparse"]["recall"] == 0.0
    assert scores["recall"]["no_headers"]["recall"] is None
    assert env.noheader_built == 0
    md = (env.out / "report.md").read_text(encoding="utf-8")
    for s in ("## Headline", "## Ablations", "## NFR check", "NFR-5", "agent:no_sql",
              "Recall@10", "## Run metadata", "qwen3:8b"):
        assert s in md


def test_resume_skips_cached_results_and_judgments(env):
    env.run("--skip-noheader")
    n_sys, n_llm, n_ret = len(env.calls), len(env.llm_calls), len(env.retrieve_calls)
    assert n_llm > 0
    env.run("--skip-noheader")
    assert (len(env.calls), len(env.llm_calls), len(env.retrieve_calls)) == \
        (n_sys, n_llm, n_ret)


def test_errors_rerun_only_with_retry_errors(env):
    env.fail.add("Intel R&D FY2024?")
    env.run("--skip-noheader", "--skip-judge", "--systems", "agent")
    assert len(env.calls) == 4
    env.fail.clear()
    env.run("--skip-noheader", "--skip-judge", "--systems", "agent")
    assert len(env.calls) == 4
    env.run("--skip-noheader", "--skip-judge", "--systems", "agent", "--retry-errors")
    assert len(env.calls) == 5 and env.calls[-1][1] == "Intel R&D FY2024?"
    rr = RunResult.model_validate_json(
        (env.out / "raw" / "agent" / "num-1.json").read_text())
    assert rr.error is None


def test_ablation_override_applied_and_restored(env):
    env.run("--skip-noheader", "--skip-judge")
    # agent:no_sql calls the base "agent" callable under the settings override
    agent_calls = [(q, d) for s, q, d in env.calls if s == "agent"]
    no_sql = [q for q, d in agent_calls if d == ["sql_query"]]
    assert sorted(no_sql) == ["Intel R&D FY2024?", "Which semis raised R&D share?"]
    assert sum(d == [] for _, d in agent_calls) == 4
    assert get_settings().agent_disabled_tools == []


def test_report_only_uses_caches(env, monkeypatch):
    env.run("--skip-noheader")
    before = json.loads((env.out / "scores.json").read_text(encoding="utf-8"))
    (env.out / "report.md").unlink()

    def boom(*a, **k):
        raise AssertionError("must not run")
    monkeypatch.setattr(sysmod, "SYSTEMS", {"agent": boom, "baseline": boom})
    monkeypatch.setattr(sysmod, "retrieve", boom)
    monkeypatch.setattr(llm, "chat_json", boom)
    assert env.run("--report-only", "--skip-noheader") == 0
    after = json.loads((env.out / "scores.json").read_text(encoding="utf-8"))
    assert (env.out / "report.md").exists()
    assert after["summary"] == before["summary"] and after["nfr"] == before["nfr"]


def test_skip_judge_leaves_text_not_judged(env):
    env.run("--skip-noheader", "--skip-judge")
    assert env.llm_calls == []
    s = json.loads((env.out / "scores.json").read_text(encoding="utf-8"))["summary"]
    assert s["agent"]["text"]["accuracy"] is None and s["agent"]["text"]["not_judged"] == 1
    assert s["agent"]["number"]["accuracy"] == 1.0


def test_noheader_collection_built_when_not_skipped(env):
    env.run("--skip-judge")
    assert env.noheader_built == 1
    s = json.loads((env.out / "scores.json").read_text(encoding="utf-8"))
    assert s["recall"]["no_headers"]["recall"] == 1.0


def test_changed_answer_invalidates_judgment(env):
    env.run("--skip-noheader", "--systems", "agent")
    n = len(env.llm_calls)
    p = env.out / "raw" / "agent" / "txt-1.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["response"]["answer"] = "Something else entirely."
    p.write_text(json.dumps(d), encoding="utf-8")
    env.run("--skip-noheader", "--systems", "agent")
    assert len(env.llm_calls) == n + 2   # correctness + faithfulness for txt-1 only


def test_edited_gold_invalidates_judgment_and_edited_question_reruns(env):
    # the user reviews the dataset after a run: edits must not reuse stale caches
    env.run("--skip-noheader", "--systems", "agent")
    n_llm, n_sys = len(env.llm_calls), len(env.calls)
    items = [json.loads(line) for line in env.ds.read_text(encoding="utf-8").splitlines()]
    txt = next(i for i in items if i["id"] == "txt-1")
    txt["gold_answer"] = txt["gold_answer"] + " (edited)"
    env.ds.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")
    env.run("--skip-noheader", "--systems", "agent")
    assert len(env.calls) == n_sys                  # same question: run reused
    assert len(env.llm_calls) == n_llm + 2          # gold changed: re-judged
    num = next(i for i in items if i["id"] == "num-1")
    ANSWERS["Intel R&D in FY2024?"] = ANSWERS[num["question"]]
    num["question"] = "Intel R&D in FY2024?"
    env.ds.write_text("\n".join(json.dumps(i) for i in items), encoding="utf-8")
    env.run("--skip-noheader", "--systems", "agent", "--skip-judge")
    assert env.calls[-1][1] == "Intel R&D in FY2024?"   # question changed: re-run
    del ANSWERS["Intel R&D in FY2024?"]


# ---- scoring rules and NFR logic --------------------------------------------------------

def _rr(system="agent", answer="x", error=None, route="agent", wall=10.0):
    resp = None if error else _response(answer, None, None)
    return RunResult(qid="q", system=system, response=resp, error=error, route=route,
                     wall_s=wall)


def _it(**kw):
    from evals.schema import DatasetItem
    return DatasetItem.model_validate({"id": "q", "question": "Q?", "gold_answer": "g", **kw})


def test_score_result_rules():
    num = _it(type="number", gold_value=5.0, unit="%")
    assert report.score_result(num, _rr(answer="It was 5.0%."), None)["score"] == 1.0
    assert report.score_result(num, _rr(answer="Not found in the filings."), None)["score"] == 0
    assert report.score_result(num, _rr(error="boom"), None)["score"] == 0
    na = _it(type="unanswerable")
    assert report.score_result(na, _rr(answer="Not found in the filings."), None)["score"] == 1
    assert report.score_result(na, _rr(answer="It was $5 billion."), None)["score"] == 0
    txt = _it(type="text")
    assert report.score_result(txt, _rr(answer="Because."), None)["score"] is None
    j = {"correctness": {"score": 0.5, "reason": "r"}, "faithfulness": {"score": 0.8}}
    row = report.score_result(txt, _rr(answer="Because."), j)
    assert row["score"] == 0.5 and row["faithfulness"] == 0.8
    assert not report.needs_judge(txt, _rr(answer="Not found in the filings."))
    mh = _it(type="multihop", gold_value=-4.34, unit="pp")
    row = report.score_result(mh, _rr(answer="Fell 4.34 pp."), {"correctness": {"score": 0}})
    assert row["numeric_match"] is True and row["score"] == 0


def _summary(acc=None, faith=None, p50=None, p95=None):
    return {"accuracy": acc, "faithfulness": faith, "p50_s": p50, "p95_s": p95}


def _nfr(agg, recall=None, rows=()):
    return {n["id"]: n["status"] for n in report.nfr_check(agg, recall or {}, list(rows))}


def _fast_rows(*walls):
    return [{"system": "agent", "route": "fast", "error": None, "wall_s": w} for w in walls]


def test_nfr_pass():
    agg = {"agent": {"overall": _summary(acc=0.85, faith=0.96),
                     "multihop": _summary(acc=0.8, p50=50, p95=110)},
           "baseline": {"multihop": _summary(acc=0.5)}}
    st = _nfr(agg, {"full": {"recall": 0.9}}, _fast_rows(3, 4, 9))
    assert st == {"NFR-1": "PASS", "NFR-2": "PASS", "NFR-3": "PASS", "NFR-4": "PASS",
                  "NFR-5": "PASS"}


def test_nfr_fail_and_na():
    agg = {"agent": {"overall": _summary(acc=0.85, faith=0.94),
                     "multihop": _summary(acc=0.7, p50=50, p95=130)},
           "baseline": {"multihop": _summary(acc=0.5)}}   # gap 20 pts < 25
    st = _nfr(agg, {"full": {"recall": 0.84}}, _fast_rows(5, 6))
    assert st == {"NFR-1": "FAIL", "NFR-2": "FAIL", "NFR-3": "FAIL", "NFR-4": "FAIL",
                  "NFR-5": "FAIL"}
    assert set(_nfr({}).values()) == {"N/A"}
    agg["agent"]["overall"]["accuracy"] = 0.79
    agg["baseline"]["multihop"]["accuracy"] = 0.1
    assert _nfr(agg)["NFR-1"] == "FAIL"


def test_failure_causes():
    rec = {"full": {"ranks": {"txt": None}}}
    items = {i: _it(id=i, type=t, gold_value=gv, unit="%") for i, t, gv in
             [("err", "number", 1.0), ("ref", "number", 1.0), ("na", "unanswerable", None),
              ("txt", "text", None), ("num", "number", 1.0), ("mh", "multihop", None)]}
    rows = [report.score_result(items["err"], _rr(error="x"), None),
            report.score_result(items["ref"], _rr(answer="Not found in the filings."), None),
            report.score_result(items["na"], _rr(answer="It was 3%."), None),
            report.score_result(items["txt"], _rr(answer="Wrong."), {"correctness":
                                                                     {"score": 0}}),
            report.score_result(items["num"], _rr(answer="It was 7%."), None),
            report.score_result(items["mh"], _rr(answer="Partly."), {"correctness":
                                                                     {"score": 0.5}})]
    for r, q in zip(rows, items, strict=True):
        r["qid"] = q
    causes = {f["qid"]: f["cause"] for f in report.failures(rows, items, rec)}
    assert causes == {"err": "exception/tool error", "ref": "refused but answerable",
                      "na": "answered unanswerable", "txt": "retrieval miss",
                      "num": "wrong number", "mh": "judge-partial"}


def test_stratified_subset_is_even_and_deterministic():
    from evals.schema import DatasetItem
    items = [DatasetItem(id=f"num-{i:03d}", type="number", question=f"q{i}", gold_answer="a")
             for i in range(40)]
    items += [DatasetItem(id=f"na-{i:03d}", type="unanswerable", question=f"n{i}",
                          gold_answer="a") for i in range(10)]
    pick = run_eval.stratified(items, run_eval.parse_per_type("number=10,unanswerable=4"))
    nums = [p.id for p in pick if p.type == "number"]
    assert len(nums) == 10 and nums[0] == "num-000" and nums[-1] == "num-039"
    assert len({p.id for p in pick}) == len(pick) == 14
    assert pick == run_eval.stratified(items, run_eval.parse_per_type("number=10,unanswerable=4"))
    assert sum(1 for p in run_eval.stratified(items, run_eval.parse_per_type("quick"))
               if p.type == "number") == 10
