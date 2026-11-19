import httpx
import pytest

from tests.ui.conftest import API, FINAL, STEPS, down_handler, happy_handler, sse
from ui import client


def test_stream_calls_on_step_in_order_and_returns_final(stub_api):
    calls = stub_api(happy_handler)
    seen = []
    resp = client.ask(API, "q", seen.append)
    assert seen == STEPS
    assert resp == FINAL
    assert calls == ["POST /ask/stream"]


@pytest.mark.parametrize("code", [404, 501])
def test_falls_back_to_ask_when_stream_missing(stub_api, code):
    def handler(request):
        if request.url.path == "/ask/stream":
            return httpx.Response(code, json={"detail": "track-b"})
        return httpx.Response(200, json=FINAL)

    calls = stub_api(handler)
    seen = []
    assert client.ask(API, "q", seen.append) == FINAL
    assert seen == STEPS
    assert calls == ["POST /ask/stream", "POST /ask"]


def test_error_event_raises(stub_api):
    body = sse([{"type": "step", "data": STEPS[0]},
                {"type": "error", "data": {"message": "Ollama timed out"}}])
    stub_api(lambda r: httpx.Response(200, content=body))
    with pytest.raises(client.ApiError, match="Ollama timed out"):
        client.ask(API, "q", lambda s: None)


def test_stream_without_final_raises(stub_api):
    stub_api(lambda r: httpx.Response(200, content=sse([{"type": "step", "data": STEPS[0]}])))
    with pytest.raises(client.ApiError, match="without a final"):
        client.ask(API, "q", lambda s: None)


def test_http_error_raises_with_status(stub_api):
    stub_api(lambda r: httpx.Response(500, text="Internal Server Error"))
    with pytest.raises(client.ApiError, match="HTTP 500"):
        client.ask(API, "q", lambda s: None)


def test_connection_refused_message(stub_api):
    stub_api(down_handler)
    with pytest.raises(client.ApiError) as e:
        client.ask(API, "q", lambda s: None)
    assert f"API not reachable at {API}" in str(e.value)
    assert "uvicorn src.api.main:app" in str(e.value)


def test_health(stub_api):
    stub_api(happy_handler)
    assert client.health(API) is None
    stub_api(down_handler)
    assert "not reachable" in client.health(API)
