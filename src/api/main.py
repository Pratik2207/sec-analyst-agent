"""FastAPI app. POST /ask routes each question (FR-18): simple single-fact number
questions take the fast path (one SQL tool call + templated, cited answer); everything
else goes to the LangGraph agent (plan -> tools -> grade -> answer -> verify).

Run: uv run uvicorn src.api.main:app --port 8000
"""

import time

from fastapi import FastAPI

from src.agent import fast_path, graph, router
from src.api.schemas import AskRequest, AskResponse, Step

app = FastAPI(title="SEC Filings Analyst")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
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
    return resp
