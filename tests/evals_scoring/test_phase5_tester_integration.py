"""Phase 5 tester integration: run_eval end to end on the real dataset (quick stratified
subset) with stubbed systems/judge/retriever, and index_chunks(use_headers=False) against a
throwaway test_ Qdrant collection."""

import json
import uuid
from pathlib import Path

import pytest

from evals import run_eval
from evals import systems as sysmod
from evals.schema import RunResult, load_dataset
from evals.scoring import judge as judge_mod
from src.api.schemas import AskResponse, Citation, Tokens

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "chunks_sample.jsonl"


@pytest.fixture
def stubbed(tmp_path, monkeypatch):
    golds = {it.question: it for it in load_dataset()}
    calls = []

    def make(name):
        def fn(question):
            calls.append((name, question))
            it = golds[question]
            src = it.gold_sources[0] if it.gold_sources else None
            cits = [Citation(ticker=src.ticker, form="10-K", fiscal_year=src.fiscal_year,
                             section="Item 8", accession_no="a", url="u")] if src else []
            text = it.gold_answer if name == "agent" else "Not found in the filings."
            resp = AskResponse(answer=text, citations=cits, steps=[],
                               tokens=Tokens(prompt=1, completion=1), latency_ms=1)
            return RunResult(qid="", system=name, response=resp, contexts=[it.gold_answer],
                             route="fast" if it.type == "number" else "agent", wall_s=2.0)
        return fn

    monkeypatch.setattr(sysmod, "SYSTEMS", {"agent": make("agent"),
                                            "baseline": make("baseline")})
    monkeypatch.setattr(sysmod, "retrieve", lambda q, c: [])
    monkeypatch.setattr(sysmod, "ensure_noheader_collection", lambda: 0)
    monkeypatch.setattr(judge_mod, "judge", lambda q, g, a: {"score": 1.0, "reason": "ok"})
    monkeypatch.setattr(run_eval, "faithfulness", lambda a, c: {"score": 1.0})
    monkeypatch.setattr(run_eval, "RESULTS_DIR", tmp_path)
    return tmp_path, calls


def test_quick_run_end_to_end_on_real_dataset(stubbed):
    out_dir, calls = stubbed
    assert run_eval.main(["--run-id", "t", "--per-type", "quick"]) == 0
    scores = json.loads((out_dir / "t" / "scores.json").read_text(encoding="utf-8"))
    md = (out_dir / "t" / "report.md").read_text(encoding="utf-8")
    meta = scores["meta"]
    assert meta["counts"] == {"number": 10, "text": 10, "multihop": 8, "unanswerable": 4}
    # agent + baseline on 32, agent:no_sql on number+multihop (18)
    assert len(calls) == 32 + 32 + 18
    agent = scores["summary"]["agent"]
    # the gold answer itself must score 100% (number golds re-parsed by number_correct)
    assert agent["number"]["accuracy"] == 1.0
    assert agent["multihop"]["numeric_match"] == 1.0
    assert scores["summary"]["baseline"]["unanswerable"]["accuracy"] == 1.0
    for typ in ("number", "text", "multihop", "unanswerable"):
        assert f"| {typ} | agent |" in md and f"| {typ} | baseline |" in md
    status = {n["id"]: n["status"] for n in scores["nfr"]}
    assert status["NFR-1"] == "PASS" and status["NFR-4"] == "PASS"
    assert status["NFR-3"] == "FAIL"   # stub retriever returns nothing: recall 0%
    # resume: a second run makes no system calls
    calls.clear()
    assert run_eval.main(["--run-id", "t", "--per-type", "quick"]) == 0
    assert calls == []


def test_all_number_and_multihop_golds_score_correct_against_themselves():
    """number_correct must accept each item's own gold_answer text (sanity check that the
    scorer and the golds agree on scale/sign)."""
    from evals.scoring.numbers import number_correct
    bad = [it.id for it in load_dataset() if it.gold_value is not None
           and not number_correct(it.gold_answer, it.gold_value, it.unit)]
    assert bad == []


@pytest.mark.integration
def test_index_chunks_without_headers_stores_body_text():
    from src.ingest.chunk_schema import chunk_body, point_id, read_chunks
    from src.ingest.index_qdrant import index_chunks
    from src.retrieval.models import qdrant

    try:
        qdrant().get_collections()
    except Exception as e:
        pytest.skip(f"qdrant not reachable: {e}")
    chunks = list(read_chunks(FIXTURE))
    name = f"test_phase5_noheader_{uuid.uuid4().hex[:8]}"
    try:
        assert index_chunks([FIXTURE], collection=name, use_headers=False) == len(chunks)
        pts = {str(p.id): p.payload for p in qdrant().scroll(name, limit=100)[0]}
        for c in chunks:
            payload = pts[point_id(c["accession_no"], c["item"], c["chunk_index"])]
            assert payload["text"] == chunk_body(c)
            assert not payload["text"].startswith("[")
            assert c["header"] not in payload["text"]
    finally:
        qdrant().delete_collection(name)
