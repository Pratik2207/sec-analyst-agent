"""Phase 6 tester, live: the running `docker compose up -d` stack (api :8000, ui :8501) and
Ollama on the host. Two LLM questions in total (one fast, one agent), run sequentially."""

import time

import httpx
import pytest

from ui.sse import iter_events

pytestmark = pytest.mark.integration

API = "http://localhost:8000"
UI = "http://localhost:8501"


@pytest.fixture(scope="module", autouse=True)
def stack_up():
    try:
        httpx.get(f"{API}/health", timeout=3)
    except httpx.HTTPError as e:
        pytest.skip(f"api not running: {e}")


def test_health():
    r = httpx.get(f"{API}/health", timeout=5)
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_ui_serves():
    r = httpx.get(UI, timeout=10)
    assert r.status_code == 200
    assert "streamlit" in r.text.lower() or "<div id=\"root\"" in r.text


def test_ask_fast_question():
    r = httpx.post(f"{API}/ask", json={"question": "What was Intel's R&D expense in FY2024?"},
                   timeout=180)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"answer", "citations", "steps", "tokens", "latency_ms"}
    assert body["steps"][0]["name"] == "route"
    assert body["steps"][0]["detail"]["kind"] == "fast"
    assert body["citations"] and body["citations"][0]["ticker"] == "INTC"
    assert body["citations"][0]["url"].startswith("https://www.sec.gov/")


def test_ask_stream_agent_question_steps_arrive_before_final():
    q = "What drove the increase in NVIDIA's gross margin in fiscal 2024?"
    arrivals: list[tuple[str, float]] = []
    events: list[dict] = []
    t0 = time.perf_counter()
    with httpx.Client(timeout=httpx.Timeout(10.0, read=400.0)) as c:
        with c.stream("POST", f"{API}/ask/stream", json={"question": q}) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            for ev in iter_events(r.iter_lines()):
                events.append(ev)
                arrivals.append((ev["type"], time.perf_counter() - t0))
    types = [e["type"] for e in events]
    assert "error" not in types, events[-1]
    assert types.count("final") == 1 and types[-1] == "final"
    steps = [e for e in events if e["type"] == "step"]
    assert len(steps) >= 3
    assert steps[0]["data"]["name"] == "route" and steps[0]["data"]["detail"]["kind"] == "agent"
    # live: the first steps arrive well before the final (not all buffered at the end)
    first_step_t = arrivals[0][1]
    final_t = arrivals[-1][1]
    assert final_t - first_step_t > 1.0, arrivals
    final = events[-1]["data"]
    assert "tool_results" not in final and all(set(e) == {"type", "data"} for e in events)
    assert final["citations"], final["answer"]
    assert all(c["url"].startswith("https://") for c in final["citations"])
