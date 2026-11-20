"""A real LangfuseTracer whose spans go to an in-memory OpenTelemetry exporter (no server)."""

import json
import uuid
from types import SimpleNamespace

import pytest
from langfuse import Langfuse
from opentelemetry import context as otel_context
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.observability.langfuse_tracer import LangfuseTracer


@pytest.fixture
def lf():
    """SimpleNamespace(tracer, spans()): spans() flushes and returns {name: span}."""
    exporter = InMemorySpanExporter()
    # The SDK keeps one set of resources per public key: a fresh key isolates each test.
    client = Langfuse(public_key=f"pk-lf-{uuid.uuid4()}", secret_key="sk-lf-test",
                      host="http://127.0.0.1:9", span_exporter=exporter,
                      tracer_provider=TracerProvider())

    def spans() -> dict:
        client.flush()
        return {s.name: s for s in exporter.get_finished_spans()}

    # Start from an empty OpenTelemetry context: an earlier test that built a production
    # Langfuse client can leave a current span behind in this thread, which would become
    # the parent of this test's root "ask" span (order-dependent failure, Phase 6 tester).
    token = otel_context.attach(otel_context.Context())
    try:
        yield SimpleNamespace(tracer=LangfuseTracer(client), spans=spans)
    finally:
        otel_context.detach(token)
        client.shutdown()


def attr(span, key: str):
    """A Langfuse attribute, JSON-decoded when it is JSON."""
    v = span.attributes[f"langfuse.observation.{key}"]
    try:
        return json.loads(v)
    except (TypeError, json.JSONDecodeError):
        return v
