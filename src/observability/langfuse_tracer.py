"""LangfuseTracer: the Tracer protocol (observability.tracing) on the Langfuse v3+ SDK (NFR-12).

The SDK is OpenTelemetry-based: `start_as_current_observation` makes the new observation
the current OTel span (a contextvar), so spans and generations opened later in the same
context become its children. The hooks never pass parents around; nesting follows the
current context.

Never breaks /ask: every SDK call is guarded. A failing call becomes a no-op and the first
failure is logged once. Export to the server happens in the SDK's background thread, so a
down server or bad keys never raise here.
"""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

from src.api.schemas import Tokens

log = logging.getLogger(__name__)


class _Handle:
    def __init__(self, tracer: "LangfuseTracer", obs: Any):
        self._tracer, self._obs = tracer, obs

    def update(self, output: Any = None, metadata: dict | None = None) -> None:
        if self._obs is None:
            return
        try:
            self._obs.update(output=output, metadata=metadata)
        except Exception as e:
            self._tracer._failed(e)


class LangfuseTracer:
    def __init__(self, client: Any):
        self._client = client
        self._warned = False

    def _failed(self, e: Exception) -> None:
        if not self._warned:
            self._warned = True
            log.warning("Langfuse tracing error (tracing calls become no-ops): %s: %s",
                        type(e).__name__, e)

    @contextmanager
    def _observe(self, name: str, input: Any):
        cm = obs = None
        try:
            cm = self._client.start_as_current_observation(name=name, as_type="span",
                                                           input=input)
            obs = cm.__enter__()
        except Exception as e:
            self._failed(e)
            cm = None
        try:
            yield _Handle(self, obs)
        except BaseException as e:   # incl. GeneratorExit when a stream client disconnects
            self._exit(cm, type(e), e, e.__traceback__)
            raise
        else:
            self._exit(cm, None, None, None)

    def _exit(self, cm: Any, *exc: Any) -> None:
        if cm is None:
            return
        try:
            cm.__exit__(*exc)
        except Exception as e:
            self._failed(e)

    @contextmanager
    def trace(self, name: str, input: Any = None):
        """The root observation of one request; flushed (in the background) when it ends."""
        try:
            with self._observe(name, input) as h:
                yield h
        finally:
            self.flush()

    def span(self, name: str, input: Any = None):
        return self._observe(name, input)

    def generation(self, name: str, model: str, input: Any, output: Any, usage: Tokens,
                   latency_s: float) -> None:
        """One finished LLM call. The hook runs after the call, so the observation's start
        is moved back by latency_s: Langfuse then shows the call where it happened, with
        latency = end - start."""
        try:
            gen = self._client.start_observation(
                name=name, as_type="generation", model=model, input=input, output=output,
                usage_details={"input": usage.prompt, "output": usage.completion})
            otel_span = getattr(gen, "_otel_span", None)   # SDK internal; best effort
            if otel_span is not None and hasattr(otel_span, "_start_time"):
                otel_span._start_time = time.time_ns() - int(latency_s * 1e9)
            gen.end()
        except Exception as e:
            self._failed(e)

    def flush(self) -> None:
        """Non-blocking: export pending observations from a daemon thread."""
        def run() -> None:
            try:
                self._client.flush()
            except Exception as e:
                self._failed(e)

        threading.Thread(target=run, name="langfuse-flush", daemon=True).start()


def create_tracer(host: str, public_key: str, secret_key: str) -> LangfuseTracer:
    from langfuse import Langfuse   # imported only when tracing is configured

    return LangfuseTracer(Langfuse(public_key=public_key, secret_key=secret_key, host=host))
