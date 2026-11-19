"""FastAPI app. POST /ask routes each question (FR-18): simple single-fact number
questions take the fast path (one SQL tool call + templated, cited answer); everything
else goes to the LangGraph agent (plan -> tools -> grade -> answer -> verify).
POST /ask/stream streams the same pipeline's steps as Server-Sent Events (FR-19).
Every request is one trace when Langfuse is configured (NFR-12).

Run: uv run uvicorn src.api.main:app --port 8000
"""

import logging
import time

from fastapi import FastAPI

from config.settings import get_settings
from src.agent import fast_path, graph, router
from src.api import stream
from src.api.schemas import AskRequest, AskResponse, Step
from src.observability.tracing import get_tracer

log = logging.getLogger("uvicorn.error")

app = FastAPI(title="SEC Filings Analyst")
app.include_router(stream.router)


@app.on_event("startup")
def _warn_on_ablation_settings() -> None:
    # Phase 5 security note: ablation switches are settings (env/.env); a stray value would
    # silently degrade every answer.
    s = get_settings()
    if s.agent_disabled_tools or not s.search_use_reranker or not s.search_use_sparse:
        log.warning("ABLATION SETTINGS ACTIVE: agent_disabled_tools=%s search_use_reranker=%s "
                    "search_use_sparse=%s", s.agent_disabled_tools, s.search_use_reranker,
                    s.search_use_sparse)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    tracer = get_tracer()
    with tracer.trace("ask", {"question": req.question}) as t:
        start = time.perf_counter()
        r = router.route(req.question)
        route_step = Step(name="route", detail={"kind": r.kind, "reason": r.reason})
        if r.kind == "fast":
            resp = fast_path.answer(req.question, r)
        else:
            resp = graph.run_agent(req.question)
            resp.steps = [route_step, *resp.steps]
            resp.tokens.prompt += r.tokens.prompt
            resp.tokens.completion += r.tokens.completion
        # end-to-end latency: routing + answering
        resp.latency_ms = int((time.perf_counter() - start) * 1000)
        t.update(output={"answer": resp.answer, "citations": len(resp.citations)},
                 metadata={"route": r.kind, "latency_ms": resp.latency_ms,
                           "tokens": resp.tokens.model_dump()})
    return resp
