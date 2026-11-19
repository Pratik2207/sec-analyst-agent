"""LangfuseTracer and get_tracer (NFR-12): what Langfuse receives, and that it never breaks /ask."""

import logging
from types import SimpleNamespace

import pytest

from src.api.schemas import Tokens
from src.observability import langfuse_tracer, tracing
from src.observability.langfuse_tracer import LangfuseTracer
from src.observability.tracing import NoopTracer
from tests.observability.conftest import attr


@pytest.fixture
def settings(monkeypatch):
    def use(public=None, secret=None):
        s = SimpleNamespace(langfuse_host="http://127.0.0.1:9", langfuse_public_key=public,
                            langfuse_secret_key=secret, tracing_enabled=bool(public and secret))
        monkeypatch.setattr(tracing, "get_settings", lambda: s)
        tracing.get_tracer.cache_clear()
    yield use
    tracing.get_tracer.cache_clear()


def test_noop_tracer_without_keys(settings):
    settings()
    assert isinstance(tracing.get_tracer(), NoopTracer)
    settings(public="pk-lf-x")   # one key is not enough
    assert isinstance(tracing.get_tracer(), NoopTracer)


def test_langfuse_tracer_with_keys(settings, monkeypatch):
    settings(public="pk-lf-x", secret="sk-lf-x")
    monkeypatch.setattr(langfuse_tracer, "create_tracer",
                        lambda host, pk, sk: ("tracer", host, pk, sk))
    assert tracing.get_tracer() == ("tracer", "http://127.0.0.1:9", "pk-lf-x", "sk-lf-x")


def test_create_tracer_builds_a_langfuse_client():
    t = langfuse_tracer.create_tracer("http://127.0.0.1:9", "pk-lf-create", "sk-lf-create")
    assert isinstance(t, LangfuseTracer)
    t._client.shutdown()


def test_noop_tracer_when_client_cannot_be_created(settings, monkeypatch):
    settings(public="pk-lf-x", secret="sk-lf-x")

    def boom(*a):
        raise RuntimeError("bad host")

    monkeypatch.setattr(langfuse_tracer, "create_tracer", boom)
    assert isinstance(tracing.get_tracer(), NoopTracer)


class _Broken:
    def __getattr__(self, name):
        def fail(*a, **k):
            raise ConnectionError(f"{name}: langfuse down")
        return fail


def test_sdk_failures_are_swallowed_and_logged_once(caplog):
    t = LangfuseTracer(_Broken())
    with caplog.at_level(logging.WARNING, logger=langfuse_tracer.__name__):
        with t.trace("ask", {"q": 1}) as h:
            with t.span("tool:sql_query", {"sql": "x"}) as s:
                s.update(output={"ok": True})
            t.generation("llm:m", "m", input="i", output="o", usage=Tokens(), latency_s=0.1)
            h.update(output={"answer": "a"})
        t.flush()
    warnings = [r for r in caplog.records if "Langfuse tracing error" in r.getMessage()]
    assert len(warnings) == 1


def test_failing_exit_and_update_are_swallowed():
    class Obs:
        def update(self, **k):
            raise ValueError("update")

    class Cm:
        def __enter__(self):
            return Obs()

        def __exit__(self, *exc):
            raise ValueError("exit")

    class Client:
        def start_as_current_observation(self, **k):
            return Cm()

        def flush(self):
            pass

    t = LangfuseTracer(Client())
    with t.trace("ask") as h:
        h.update(output="x")


def test_app_errors_still_propagate(lf):
    with pytest.raises(KeyError):
        with lf.tracer.trace("ask"):
            with lf.tracer.span("tool:sql_query"):
                raise KeyError("app bug")
    spans = lf.spans()
    assert set(spans) == {"ask", "tool:sql_query"}   # both observations were still ended


def test_trace_span_generation_nesting_and_attributes(lf):
    t = lf.tracer
    with t.trace("ask", {"question": "Intel R&D FY2024?"}) as h:
        with t.span("tool:sql_query", {"sql": "SELECT 1"}) as s:
            s.update(output={"ok": True, "items": 1, "error": None},
                     metadata={"sql": "SELECT 1"})
            t.generation("llm:qwen3:4b", "qwen3:4b", input={"user": "u"}, output="plan text",
                         usage=Tokens(prompt=120, completion=30), latency_s=1.5)
        t.generation("llm:qwen3:1.7b", "qwen3:1.7b", input={"user": "g"}, output="ok",
                     usage=Tokens(prompt=7, completion=2), latency_s=0.25)
        h.update(output={"answer": "a", "citations": 1},
                 metadata={"route": "agent", "latency_ms": 1800,
                           "tokens": {"prompt": 127, "completion": 32}})
    spans = lf.spans()
    root, tool = spans["ask"], spans["tool:sql_query"]
    gen_in_tool, gen_in_root = spans["llm:qwen3:4b"], spans["llm:qwen3:1.7b"]

    # one trace; nesting follows the current context
    assert root.parent is None
    assert {s.context.trace_id for s in spans.values()} == {root.context.trace_id}
    assert tool.parent.span_id == root.context.span_id
    assert gen_in_tool.parent.span_id == tool.context.span_id
    assert gen_in_root.parent.span_id == root.context.span_id

    # the trace: input, output, metadata (route, latency, tokens)
    assert attr(root, "input") == {"question": "Intel R&D FY2024?"}
    assert attr(root, "output") == {"answer": "a", "citations": 1}
    assert attr(root, "metadata.route") == "agent"
    assert attr(root, "metadata.latency_ms") == 1800
    assert attr(root, "metadata.tokens") == {"prompt": 127, "completion": 32}

    # the tool span: input, output, metadata
    assert attr(tool, "type") == "span"
    assert attr(tool, "input") == {"sql": "SELECT 1"}
    assert attr(tool, "output") == {"ok": True, "items": 1, "error": None}
    assert attr(tool, "metadata.sql") == "SELECT 1"

    # the generation: model, usage, latency (end - start)
    assert attr(gen_in_tool, "type") == "generation"
    assert attr(gen_in_tool, "model.name") == "qwen3:4b"
    assert attr(gen_in_tool, "usage_details") == {"input": 120, "output": 30}
    assert attr(gen_in_tool, "input") == {"user": "u"}
    assert attr(gen_in_tool, "output") == "plan text"
    assert (gen_in_tool.end_time - gen_in_tool.start_time) / 1e9 == pytest.approx(1.5, abs=0.05)
    assert (gen_in_root.end_time - gen_in_root.start_time) / 1e9 == pytest.approx(0.25,
                                                                                  abs=0.05)
