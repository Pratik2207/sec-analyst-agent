"""POST /ask/stream (FR-19): SSE wire format, routing, patching, errors, and the trace
surviving the streaming generator. Router, fast path tool and graph are stubbed."""

import json

import pytest
from fastapi.testclient import TestClient

from src.agent import graph, router
from src.agent.router import FactQuery, Route
from src.api import main, stream
from src.api.schemas import AskResponse, Step, Tokens
from src.observability.tracing import NoopTracer
from src.tools import sql_tool
from src.tools.types import Source, ToolResult, edgar_index_url
from tests.observability.conftest import attr

ACCN = "0000050863-25-000009"
ROW = {"name": "Intel", "value": 16_546_000_000.0, "period_end": "2024-12-28",
       "xbrl_tag": "ResearchAndDevelopmentExpense", "accession_no": ACCN,
       "source_id": f"xbrl:{ACCN}"}
SOURCE = Source(source_id=f"xbrl:{ACCN}", kind="xbrl", ticker="INTC", form="10-K",
                fiscal_year=2024, section="Item 8 Financial Statements (XBRL)",
                url=edgar_index_url("0000050863", ACCN), accession_no=ACCN)


def post(question="Why did Intel's margin fall?"):
    with TestClient(main.app) as c:
        r = c.post("/ask/stream", json={"question": question})
    raw = r.text
    assert raw.endswith("\n\n")
    msgs = raw[:-2].split("\n\n")
    assert all(m.startswith("data: ") and "\n" not in m for m in msgs)
    return r, [json.loads(m[len("data: "):]) for m in msgs]


@pytest.fixture
def tracer(monkeypatch):
    t = NoopTracer()
    monkeypatch.setattr(stream, "get_tracer", lambda: t)
    return t


@pytest.fixture
def agent(monkeypatch, tracer):
    """Agent route; the stubbed graph streams two node steps, the flags step, then final."""
    monkeypatch.setattr(router, "route", lambda q: Route(
        "agent", reason="multi-hop", tokens=Tokens(prompt=11, completion=4)))
    steps = [Step(name="plan", detail={"steps": 1}),
             Step(name="tool:sql_query", detail={"ok": True}),
             Step(name="flags", detail={"flags": []})]

    def events(question):
        for st in steps:
            yield {"type": "step", "data": st}
        yield {"type": "final", "tool_results": [{"secret": "internal"}],
               "data": AskResponse(answer="Because.", citations=[], steps=steps,
                                   tokens=Tokens(prompt=100, completion=20), latency_ms=1)}

    monkeypatch.setattr(graph, "run_agent_events", events)
    return steps


def test_agent_route_event_order_and_final(agent):
    r, evs = post()
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.headers["cache-control"] == "no-cache"
    assert r.headers["x-accel-buffering"] == "no"

    assert [e["type"] for e in evs] == ["step", "step", "step", "step", "final"]
    assert evs[0]["data"] == {"name": "route",
                              "detail": {"kind": "agent", "reason": "multi-hop"}}
    assert [e["data"] for e in evs[1:4]] == [s.model_dump() for s in agent]

    final = evs[-1]["data"]
    AskResponse.model_validate(final)
    assert final["answer"] == "Because."
    # patched like /ask: route step first, router tokens added, end-to-end latency
    assert [s["name"] for s in final["steps"]] == ["route", "plan", "tool:sql_query", "flags"]
    assert final["tokens"] == {"prompt": 111, "completion": 24}
    assert isinstance(final["latency_ms"], int)


def test_tool_results_never_sent(agent):
    r, evs = post()
    assert "tool_results" not in r.text and "internal" not in r.text
    assert all(set(e) == {"type", "data"} for e in evs)


def test_error_event_instead_of_final(monkeypatch, tracer):
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="x"))

    def events(question):
        yield {"type": "step", "data": Step(name="plan", detail={})}
        raise RuntimeError("ollama down at secret-host:11434")

    monkeypatch.setattr(graph, "run_agent_events", events)
    _, evs = post()
    assert [e["type"] for e in evs] == ["step", "step", "error"]
    assert evs[-1]["data"] == {"message": "internal error (RuntimeError)"}   # no details


def test_error_when_agent_has_no_final(monkeypatch, tracer):
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="x"))
    monkeypatch.setattr(graph, "run_agent_events", lambda q: iter(()))
    _, evs = post()
    assert [e["type"] for e in evs] == ["step", "error"]


def test_fast_route(monkeypatch, tracer):
    monkeypatch.setattr(router, "route", lambda q: Route(
        "fast", FactQuery("INTC", "rd_expense", 2024), "single fact",
        Tokens(prompt=5, completion=3)))
    monkeypatch.setattr(sql_tool, "call",
                        lambda sql: ToolResult(ok=True, data=[ROW], sources=[SOURCE]))
    monkeypatch.setattr(graph, "run_agent_events", lambda q: pytest.fail("no agent"))
    _, evs = post("Intel R&D FY2024?")
    assert [(e["type"], e["data"].get("name")) for e in evs] == [
        ("step", "route"), ("step", "sql_query"), ("final", None)]
    assert evs[0]["data"]["detail"]["kind"] == "fast"
    assert evs[1]["data"]["detail"]["rows"] == [ROW]
    final = evs[-1]["data"]
    assert final["answer"].startswith("Intel's R&D expense for fiscal year 2024")
    assert [c["accession_no"] for c in final["citations"]] == [ACCN]
    assert final["tokens"] == {"prompt": 5, "completion": 3}
    assert [s["name"] for s in final["steps"]] == ["route", "sql_query"]


def test_trace_context_survives_the_stream(monkeypatch, lf):
    """Spans opened while streaming (between yields, each pulled by a different threadpool
    call) must still be children of the request's trace."""
    t = lf.tracer
    monkeypatch.setattr(stream, "get_tracer", lambda: t)
    monkeypatch.setattr(router, "route", lambda q: Route("agent", reason="multi-hop"))

    def events(question):
        for i in range(3):
            with t.span(f"tool:step{i}", {"i": i}) as sp:
                t.generation(f"llm:{i}", "m", input="x", output="y",
                             usage=Tokens(prompt=1, completion=1), latency_s=0.01)
                sp.update(output={"ok": True})
            yield {"type": "step", "data": Step(name=f"step{i}", detail={})}
        yield {"type": "final", "tool_results": [],
               "data": AskResponse(answer="a", citations=[], steps=[],
                                   tokens=Tokens(prompt=3, completion=3), latency_ms=0)}

    monkeypatch.setattr(graph, "run_agent_events", events)
    _, evs = post()
    assert evs[-1]["type"] == "final"

    spans = lf.spans()
    root = spans["ask"]
    assert root.parent is None
    for i in range(3):
        assert spans[f"tool:step{i}"].parent.span_id == root.context.span_id
        assert spans[f"llm:{i}"].parent.span_id == spans[f"tool:step{i}"].context.span_id
    assert {s.context.trace_id for s in spans.values()} == {root.context.trace_id}
    assert attr(root, "input") == {"question": "Why did Intel's margin fall?"}
    assert attr(root, "output") == {"answer": "a", "citations": 0}
    assert attr(root, "metadata.route") == "agent"
