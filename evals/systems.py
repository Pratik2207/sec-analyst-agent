"""Phase 5 contract: the systems under evaluation and the ablation configurations.
Owned by main.

Systems return RunResult (never raise):
  agent_system(question)     the full /ask pipeline: router -> fast path or LangGraph agent
  baseline_system(question)  naive RAG (dense top-k + one LLM call)
Ablations (PRD 10):
  END_TO_END_ABLATIONS  run a system with settings overridden ("no_sql": the agent with the
                        sql_query tool disabled, i.e. text only) on the given question types
  RETRIEVAL_ABLATIONS   retrieval-only configurations scored by recall@10 (no LLM):
                        full, no_reranker, no_sparse, no_headers (separate collection)
"""

import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from config.settings import get_settings
from evals.schema import RunResult
from src.agent import evidence, fast_path, graph, router
from src.api.schemas import Step
from src.baseline import naive_rag
from src.observability.tracing import get_tracer
from src.retrieval.hybrid_search import hybrid_search

NOHEADER_COLLECTION = "filings_noheader"
RECALL_K = 10


@contextmanager
def settings_override(**overrides) -> Iterator[None]:
    """Temporarily set fields on the cached Settings object."""
    s = get_settings()
    old = {k: getattr(s, k) for k in overrides}
    try:
        for k, v in overrides.items():
            setattr(s, k, v)
        yield
    finally:
        for k, v in old.items():
            setattr(s, k, v)


def _fact_contexts(steps: list[Step]) -> list[str]:
    out = []
    for st in steps:
        for row in (st.detail or {}).get("rows", []) or []:
            if "value" in row:
                out.append(", ".join(f"{k}={v}" for k, v in row.items() if k != "source_id"))
    return out


_ITEM_HEAD = re.compile(r"^([A-Z.]{1,6})\s+FY(\d{4})")


def _ordered_contexts(items: list, resp) -> list[str]:
    """Facts and calcs first, then text from the filings the answer cites, then the rest:
    the faithfulness judge truncates contexts, and must not lose what the answer cites
    (Phase 5 review: two 8-chunk searches overflow the budget)."""
    cited = {(c.ticker, c.fiscal_year) for c in resp.citations}

    def rank(it) -> int:
        if it.kind in ("fact", "calc"):
            return 0
        m = _ITEM_HEAD.match(it.text)
        return 1 if m and (m.group(1), int(m.group(2))) in cited else 2

    return [it.text for it in sorted(items, key=rank)]


def agent_system(question: str) -> RunResult:
    # one trace per eval question when Langfuse is configured (not hundreds of fragments)
    with get_tracer().trace("eval:agent", {"question": question}):
        return _agent_system(question)


def _agent_system(question: str) -> RunResult:
    t0 = time.perf_counter()
    try:
        r = router.route(question)
        # The fast path IS a SQL lookup: with sql_query disabled (the "text only" ablation)
        # every question must go through the agent, or number questions keep using SQL.
        if r.kind == "fast" and "sql_query" in get_settings().agent_disabled_tools:
            r = router.Route("agent", reason="fast path disabled (sql_query ablation)",
                             tokens=r.tokens)
        if r.kind == "fast":
            resp = fast_path.answer(question, r)
            contexts = _fact_contexts(resp.steps)
        else:
            resp, tool_results = graph.run_agent_traced(question)
            resp.steps = [Step(name="route", detail={"kind": r.kind, "reason": r.reason}),
                          *resp.steps]
            resp.tokens.prompt += r.tokens.prompt
            resp.tokens.completion += r.tokens.completion
            contexts = _ordered_contexts(evidence.evidence_items(tool_results), resp)
        wall = time.perf_counter() - t0
        resp.latency_ms = int(wall * 1000)
        return RunResult(qid="", system="agent", response=resp, contexts=contexts,
                         route=r.kind, wall_s=wall)
    except Exception as e:   # one broken question must not stop an hours-long run
        return RunResult(qid="", system="agent", error=f"{type(e).__name__}: {e}"[:500],
                         wall_s=time.perf_counter() - t0)


def baseline_system(question: str) -> RunResult:
    t0 = time.perf_counter()
    try:
        resp, hits = naive_rag.answer_traced(question)
        return RunResult(qid="", system="baseline", response=resp,
                         contexts=[h.payload["text"] for h in hits],
                         wall_s=time.perf_counter() - t0)
    except Exception as e:
        return RunResult(qid="", system="baseline", error=f"{type(e).__name__}: {e}"[:500],
                         wall_s=time.perf_counter() - t0)


SYSTEMS: dict[str, Callable[[str], RunResult]] = {
    "agent": agent_system,
    "baseline": baseline_system,
}

# name -> (base system, settings overrides, question types it runs on)
END_TO_END_ABLATIONS: dict[str, tuple[str, dict, tuple[str, ...]]] = {
    "agent:no_sql": ("agent", {"agent_disabled_tools": ["sql_query"]},
                     ("number", "multihop")),
}

# name -> hybrid_search keyword arguments
RETRIEVAL_ABLATIONS: dict[str, dict] = {
    "full": {},
    "no_reranker": {"use_reranker": False},
    "no_sparse": {"use_sparse": False},
    "no_headers": {"collection": NOHEADER_COLLECTION},
}


def retrieve(question: str, config: str) -> list[dict]:
    """Top RECALL_K chunk payloads for a retrieval ablation (unfiltered, like a user query)."""
    return [h.payload for h in hybrid_search(question, k=RECALL_K,
                                             **RETRIEVAL_ABLATIONS[config])]


def ensure_noheader_collection() -> int:
    """Build the no-headers collection once (re-embeds every chunk body, ~25 min on CPU)."""
    from src.ingest.chunk_schema import CHUNKS_DIR
    from src.ingest.index_qdrant import index_chunks
    from src.retrieval.models import qdrant

    client = qdrant()
    if client.collection_exists(NOHEADER_COLLECTION):
        n = client.count(NOHEADER_COLLECTION, exact=True).count
        if n == client.count(get_settings().qdrant_collection, exact=True).count:
            return n
    return index_chunks(sorted(CHUNKS_DIR.glob("*.jsonl")), NOHEADER_COLLECTION,
                        use_headers=False)
