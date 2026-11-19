"""Phase 6 contract: tracing (NFR-12). Owned by main; track-b implements LangfuseTracer.

Every /ask is one trace; inside it, each tool call is a span and each LLM call a
generation (model, input, output, token usage, latency). Agent code calls only this
interface, so tracing is a no-op when Langfuse is not configured (no keys) or unreachable.

    tracer = get_tracer()
    with tracer.trace("ask", {"question": q}) as t:          # one per /ask
        with tracer.span("tool:sql_query", {"sql": ...}) as s:
            ...
            s.update(output={"rows": 3}, metadata={...})
        tracer.generation("planner", model, input=..., output=..., usage=tokens,
                          latency_s=1.2)
        t.update(output={"answer": ...}, metadata={"latency_ms": ...})
"""

from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Protocol

from src.api.schemas import Tokens


class Handle(Protocol):
    def update(self, output: Any = None, metadata: dict | None = None) -> None: ...


class Tracer(Protocol):
    def trace(self, name: str, input: Any = None): ...      # context manager -> Handle
    def span(self, name: str, input: Any = None): ...       # context manager -> Handle
    def generation(self, name: str, model: str, input: Any, output: Any, usage: Tokens,
                   latency_s: float) -> None: ...
    def flush(self) -> None: ...


class _NoopHandle:
    def update(self, output: Any = None, metadata: dict | None = None) -> None:
        pass


class NoopTracer:
    @contextmanager
    def trace(self, name: str, input: Any = None):
        yield _NoopHandle()

    @contextmanager
    def span(self, name: str, input: Any = None):
        yield _NoopHandle()

    def generation(self, name: str, model: str, input: Any, output: Any, usage: Tokens,
                   latency_s: float) -> None:
        pass

    def flush(self) -> None:
        pass


@lru_cache
def get_tracer() -> Tracer:
    """LangfuseTracer when settings.tracing_enabled, else NoopTracer. Never raises: a
    Langfuse problem must not break /ask. [track-b fills in the Langfuse branch]"""
    return NoopTracer()
