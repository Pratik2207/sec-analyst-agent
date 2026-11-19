"""A stub API for the UI tests: httpx.Client is patched to use an in-memory transport."""

import json

import httpx
import pytest

from config.settings import get_settings

API = "http://stub-api:8000"

STEPS = [
    {"name": "route", "detail": {"kind": "agent", "reason": "multi-hop"}},
    {"name": "plan", "detail": {"steps": [{"tool": "sql_query"}, {"tool": "calculate"}]}},
    {"name": "tool_call", "detail": {"step": 0, "tool": "sql_query", "ok": True, "rows": 24}},
    {"name": "tool_call", "detail": {"step": 1, "tool": "calculate", "ok": True,
                                     "results": [{}, {}, {}, {}]}},
]
FINAL = {
    "answer": "Intel raised R&D intensity while its gross margin fell [1]. NVIDIA did not [2].",
    "citations": [
        {"ticker": "INTC", "form": "10-K", "fiscal_year": 2025, "section": "Item 8",
         "accession_no": "0000050863-26-000001",
         "url": "https://www.sec.gov/Archives/edgar/data/50863/intc-2025.htm"},
        {"ticker": "NVDA", "form": "10-K", "fiscal_year": 2025, "section": "Item 8",
         "accession_no": "0001045810-25-000023",
         "url": "https://www.sec.gov/Archives/edgar/data/1045810/nvda-2025.htm"},
    ],
    "steps": STEPS,
    "tokens": {"prompt": 1234, "completion": 210},
    "latency_ms": 42000,
}


def sse(events: list[dict]) -> bytes:
    return b"".join(f"data: {json.dumps(e)}\n\n".encode() for e in events)


def stream_body(steps=STEPS, final=FINAL) -> bytes:
    return (b": keep-alive\n\n"
            + sse([{"type": "step", "data": s} for s in steps]
                  + [{"type": "final", "data": final}]))


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "t t@example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:change-me@127.0.0.1:1/x")
    monkeypatch.setenv("AGENT_DATABASE_URL", "postgresql://x:change-me@127.0.0.1:1/x")
    monkeypatch.setenv("API_URL", API)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def stub_api(monkeypatch):
    """Install a handler: stub_api(handler) where handler(request) -> httpx.Response.
    Records every request path in the returned list."""
    calls: list[str] = []
    real_client = httpx.Client

    def install(handler):
        def wrapped(request: httpx.Request) -> httpx.Response:
            calls.append(f"{request.method} {request.url.path}")
            return handler(request)

        def make_client(*args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(wrapped)
            return real_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "Client", make_client)
        return calls

    return install


def happy_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path == "/ask/stream":
        return httpx.Response(200, content=stream_body(),
                              headers={"content-type": "text/event-stream"})
    return httpx.Response(404)


def down_handler(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("[WinError 10061] connection refused", request=request)
