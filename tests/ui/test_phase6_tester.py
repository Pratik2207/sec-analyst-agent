"""Phase 6 tester: UI $ escaping, citation numbering, error events in the app (stubbed API)."""

import copy
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

from tests.ui.conftest import FINAL, STEPS, sse
from ui.render import citation_markdown, format_answer

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")


def test_dollar_amounts_escaped_and_markers_bolded():
    out = format_answer("Revenue was $60.9 billion [1], up from $27.0B [2][3].")
    assert out == r"Revenue was \$60.9 billion **[1]**, up from \$27.0B **[2]****[3]**."
    assert "$" not in out.replace(r"\$", "")


def test_format_answer_leaves_non_numeric_brackets():
    assert format_answer("see [a] and [10]") == "see [a] and **[10]**"


def test_citation_numbering_and_missing_fields():
    line = citation_markdown(3, {})
    assert line.startswith("**[3]** ? 10-K FY?")
    assert "EDGAR" not in line
    assert "javascript" not in citation_markdown(1, {"url": "javascript:alert(1)"})


def _handler(final=None, events=None):
    def h(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/ask/stream":
            evs = events if events is not None else (
                [{"type": "step", "data": s} for s in STEPS] + [{"type": "final", "data": final}])
            return httpx.Response(200, content=sse(evs),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(404)
    return h


def _run(stub_api, handler, question):
    stub_api(handler)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.chat_input[0].set_value(question).run()
    assert not at.exception, at.exception
    return at


def test_app_escapes_dollars_in_answer_and_question(stub_api):
    final = copy.deepcopy(FINAL)
    final["answer"] = "Intel's R&D was $16.5 billion and $17.5 billion [1]."
    at = _run(stub_api, _handler(final), "Did Intel spend $16B or $17B?")
    md = [m.value for m in at.markdown]
    assert r"Did Intel spend \$16B or \$17B?" in md
    assert any(r"\$16.5 billion and \$17.5 billion **[1]**" in m for m in md)


def test_app_source_numbers_follow_citation_order(stub_api):
    at = _run(stub_api, _handler(FINAL), "q")
    sources = [m.value for m in at.markdown if m.value.startswith("**[")]
    assert [s.split()[0] for s in sources] == ["**[1]**", "**[2]**"]
    assert "INTC" in sources[0] and "NVDA" in sources[1]


def test_app_shows_stream_error_event(stub_api):
    events = [{"type": "step", "data": STEPS[0]},
              {"type": "error", "data": {"message": "internal error (RuntimeError)"}}]
    at = _run(stub_api, _handler(events=events), "q")
    assert any("internal error (RuntimeError)" in e.value for e in at.main.error)
    assert at.session_state.history[-1].get("error")

