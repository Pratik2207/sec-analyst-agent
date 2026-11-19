"""FastAPI app. POST /ask routes each question (FR-18): simple single-fact number
questions take the fast path (one SQL tool call + templated, cited answer); everything
else goes to the agent, which arrives in Phase 4.

Run: uv run uvicorn src.api.main:app --port 8000
"""

import time

from fastapi import FastAPI

from src.agent import fast_path, router
from src.api.schemas import AskRequest, AskResponse, Step

AGENT_PENDING = ("Multi-step and explanatory questions need the full agent, which is not "
                 "available yet. Try a single number question, e.g. \"What was Intel's R&D "
                 "expense in FY2024?\"")

app = FastAPI(title="SEC Filings Analyst")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    start = time.perf_counter()
    r = router.route(req.question)
    if r.kind == "fast":
        resp = fast_path.answer(req.question, r)
    else:   # Phase 4: the LangGraph agent
        resp = AskResponse(answer=AGENT_PENDING, citations=[],
                           steps=[Step(name="route", detail={"kind": r.kind,
                                                             "reason": r.reason})],
                           tokens=r.tokens, latency_ms=0)
    # end-to-end latency: routing + answering
    resp.latency_ms = int((time.perf_counter() - start) * 1000)
    return resp
