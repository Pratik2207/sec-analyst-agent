"""POST /ask/stream: Server-Sent Events of the agent's steps as they happen (FR-19). [track-b]

Wire format (Phase 6 contract), one SSE message per event, `data: <json>\n\n`:
  {"type": "step",  "data": <Step as JSON>}          zero or more, in order
  {"type": "final", "data": <AskResponse as JSON>}   exactly one, last
  {"type": "error", "data": {"message": str}}        instead of final, if something failed
Routing as in POST /ask: fast questions emit the route + sql_query steps then final; agent
questions stream graph.run_agent_events (never send its internal "tool_results").
The whole request is one trace (observability.tracing), like POST /ask.
"""

import contextvars
import json
import logging
import time
from collections.abc import Iterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from src.agent import fast_path, graph
from src.agent import router as agent_router
from src.api.schemas import AskRequest, AskResponse, Step
from src.observability.tracing import get_tracer

log = logging.getLogger("uvicorn.error")

router = APIRouter()

HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(type_: str, data: dict) -> str:
    return f"data: {json.dumps({'type': type_, 'data': data})}\n\n"


def _step(st: Step) -> str:
    return _sse("step", st.model_dump(mode="json"))


def _events(question: str) -> Iterator[str]:
    """The /ask pipeline as SSE messages (same routing, response patching and trace)."""
    tracer = get_tracer()
    try:
        with tracer.trace("ask", {"question": question}) as t:
            start = time.perf_counter()
            r = agent_router.route(question)
            if r.kind == "fast":
                resp = fast_path.answer(question, r)
                for st in resp.steps:   # route + sql_query
                    yield _step(st)
            else:
                route_step = Step(name="route", detail={"kind": r.kind, "reason": r.reason})
                yield _step(route_step)
                resp: AskResponse | None = None
                for ev in graph.run_agent_events(question):
                    if ev["type"] == "step":
                        yield _step(ev["data"])
                    elif ev["type"] == "final":
                        resp = ev["data"]   # ev["tool_results"] is internal: never sent
                if resp is None:
                    raise RuntimeError("agent produced no final event")
                resp.steps = [route_step, *resp.steps]
                resp.tokens.prompt += r.tokens.prompt
                resp.tokens.completion += r.tokens.completion
            # end-to-end latency: routing + answering
            resp.latency_ms = int((time.perf_counter() - start) * 1000)
            t.update(output={"answer": resp.answer, "citations": len(resp.citations)},
                     metadata={"route": r.kind, "latency_ms": resp.latency_ms,
                               "tokens": resp.tokens.model_dump()})
        yield _sse("final", resp.model_dump(mode="json"))
    except Exception as e:
        # Details stay in the server log; the client gets the error type only.
        log.exception("/ask/stream failed")
        yield _sse("error", {"message": f"internal error ({type(e).__name__})"})


def _in_one_context(gen: Iterator[str]) -> Iterator[str]:
    """Run every step of `gen` inside one contextvars.Context.

    Starlette pulls a sync iterator with one threadpool call per item, each in a fresh copy
    of the request context, so a contextvar set while producing one item (the current
    trace span) would be gone for the next. Running all steps in the same Context keeps the
    trace current, so spans created later in the stream stay its children."""
    ctx = contextvars.copy_context()
    try:
        while True:
            try:
                item = ctx.run(next, gen)
            except StopIteration:
                return
            yield item
    finally:
        ctx.run(gen.close)   # client disconnect: close the trace in its own context


@router.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    return StreamingResponse(_in_one_context(_events(req.question)),
                             media_type="text/event-stream", headers=HEADERS)
