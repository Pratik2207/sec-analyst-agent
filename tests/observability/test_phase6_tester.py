"""Phase 6 tester: extra SSE wire-format cases and tracing with a dead Langfuse host.

Router / fast path / graph are stubbed; no LLM, DB or Langfuse server is used."""

import json
import time

import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.agent import fast_path, graph, router
from src.agent.router import FactQuery, Route
from src.api import main, stream
from src.api.schemas import AskResponse, Step, Tokens
from src.observability import tracing
from src.observability.langfuse_tracer import LangfuseTracer
from src.observability.tracing import NoopTracer
from ui.sse import iter_events

FINAL = AskResponse(answer="Intel spent $16.5B [1].", citations=[], steps=[
    Step(name="route", detail={"kind": "fast"}), Step(name="sql_query", detail={"ok": True})],
    tokens=Tokens(prompt=1, completion=1), latency_ms=1)


def _stream(question="q") -> list[dict]:
    with TestClient(main.app) as c:
        r = c.post("/ask/stream", json={"question": question})
    assert r.status_code == 200
    # Round trip through the UI's own SSE parser (server and client agree on the format).
    return list(iter_events(r.text.splitlines(keepends=True)))


@pytest.fixture
def noop(monkeypatch):
    monkeypatch.setattr(stream, "get_tracer", lambda: NoopTracer())


def _fast(monkeypatch):
    monkeypatch.setattr(router, "route", lambda q: Route(
        "fast", FactQuery("INTC", "rd_expense", 2024), "single fact", Tokens()))


def test_fast_path_exception_gives_single_error_and_no_final(monkeypatch, noop):
    _fast(monkeypatch)

    def boom(q, r):
        raise ConnectionError("postgres at db-secret-host:5432 refused")

    monkeypatch.setattr(fast_path, "answer", boom)
    evs = _stream()
    assert [e["type"] for e in evs] == ["error"]
    assert evs[0]["data"] == {"message": "internal error (ConnectionError)"}


def test_router_exception_gives_error_event(monkeypatch, noop):
    def boom(q):
        raise RuntimeError("router died")

    monkeypatch.setattr(router, "route", boom)
    evs = _stream()
    assert [e["type"] for e in evs] == ["error"]
    assert "router died" not in json.dumps(evs)


def test_exactly_one_final_and_it_is_last(monkeypatch, noop):
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="x"))
    steps = [Step(name=f"s{i}", detail={}) for i in range(5)]

    def events(q):
        for s in steps:
            yield {"type": "step", "data": s}
        yield {"type": "final", "data": FINAL.model_copy(deep=True), "tool_results": ["x"]}

    monkeypatch.setattr(graph, "run_agent_events", events)
    evs = _stream()
    types = [e["type"] for e in evs]
    assert types.count("final") == 1 and types[-1] == "final"
    assert "error" not in types
    assert [e["data"]["name"] for e in evs[:-1]] == ["route"] + [s.name for s in steps]


def test_agent_failure_after_final_gives_one_terminal_event(monkeypatch, noop):
    """If the agent generator raises after it produced a final, the client still gets
    exactly one terminal event (error), never final + error."""
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="x"))

    def events(q):
        yield {"type": "final", "data": FINAL.model_copy(deep=True), "tool_results": []}
        raise RuntimeError("late failure")

    monkeypatch.setattr(graph, "run_agent_events", events)
    evs = _stream()
    terminal = [e["type"] for e in evs if e["type"] in ("final", "error")]
    assert len(terminal) == 1 and evs[-1]["type"] in ("final", "error")


# ---- tracing: no keys / dead host -------------------------------------------------------

@pytest.fixture
def env(monkeypatch):
    """Settings from env only for the tracer (the real .env is still read for the rest)."""
    def use(**kv):
        for k, v in kv.items():
            monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        tracing.get_tracer.cache_clear()
    yield use
    get_settings.cache_clear()
    tracing.get_tracer.cache_clear()


def test_no_keys_means_noop(env):
    env(LANGFUSE_PUBLIC_KEY="", LANGFUSE_SECRET_KEY="")
    assert get_settings().tracing_enabled is False
    assert isinstance(tracing.get_tracer(), NoopTracer)


def test_dead_langfuse_host_does_not_break_ask_or_stream(env, monkeypatch):
    # Keys set, host unreachable (nothing listens on port 1): a real Langfuse client.
    env(LANGFUSE_PUBLIC_KEY="pk-lf-dead-host-test", LANGFUSE_SECRET_KEY="sk-lf-dead",
        LANGFUSE_HOST="http://127.0.0.1:1")
    t = tracing.get_tracer()
    assert isinstance(t, LangfuseTracer)
    _fast(monkeypatch)
    monkeypatch.setattr(fast_path, "answer", lambda q, r: FINAL.model_copy(deep=True))
    try:
        with TestClient(main.app) as c:
            t0 = time.perf_counter()
            r = c.post("/ask", json={"question": "Intel R&D FY2024?"})
            dt = time.perf_counter() - t0
            assert r.status_code == 200, r.text
            assert r.json()["answer"] == FINAL.answer
            assert dt < 5, f"/ask blocked {dt:.1f}s on a dead Langfuse host"

            r2 = c.post("/ask/stream", json={"question": "Intel R&D FY2024?"})
            evs = list(iter_events(r2.text.splitlines(keepends=True)))
            assert evs[-1]["type"] == "final"
    finally:
        t._client.shutdown()
