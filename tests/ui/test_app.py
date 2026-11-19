"""Streamlit AppTest smoke tests of ui/app.py against a stubbed API."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from tests.ui.conftest import API, down_handler, happy_handler

APP = str(Path(__file__).resolve().parents[2] / "ui" / "app.py")
QUESTION = "Which semiconductor companies raised R&D as a share of revenue?"


def run_app() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, at.exception
    return at


def markdowns(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_question_shows_answer_sources_and_trace(stub_api):
    calls = stub_api(happy_handler)
    at = run_app()
    assert "Not investment advice" in " ".join(c.value for c in at.caption)
    assert any(f"API ok at {API}" in s.value for s in at.sidebar.success)

    at.chat_input[0].set_value(QUESTION).run()
    assert not at.exception, at.exception
    assert "POST /ask/stream" in calls
    md = markdowns(at)
    assert any("Intel raised R&D intensity" in m and "**[1]**" in m for m in md)
    assert any(m.startswith("**[1]** INTC 10-K FY2025, Item 8") and
               "(https://www.sec.gov/Archives/edgar/data/50863/intc-2025.htm)" in m for m in md)
    assert any(m.startswith("**[2]** NVDA") for m in md)
    trace = [e for e in at.expander if e.label == "Agent trace"]
    assert len(trace) == 1
    trace_md = [m.value for m in trace[0].markdown]
    assert any("sql_query: 24 rows" in m for m in trace_md)
    assert any("prompt 1234" in m and "42000 ms" in m for m in trace_md)
    assert len(trace[0].json) == 4
    # live status box ended complete with the step labels written into it
    assert any("calculate: 4 results" in m for m in md)


def test_history_survives_rerun(stub_api):
    stub_api(happy_handler)
    at = run_app()
    at.chat_input[0].set_value(QUESTION).run()
    at.run()
    assert not at.exception
    assert any("Intel raised R&D intensity" in m for m in markdowns(at))
    assert len(at.session_state.history) == 2


def test_example_button_asks_question(stub_api):
    calls = stub_api(happy_handler)
    at = run_app()
    at.sidebar.button[0].click().run()
    assert not at.exception, at.exception
    assert "POST /ask/stream" in calls
    assert at.session_state.history[0]["content"] == "What was Intel's R&D expense in FY2024?"


def test_api_down_message(stub_api):
    stub_api(down_handler)
    at = run_app()
    assert any("not reachable" in e.value for e in at.sidebar.error)
    at.chat_input[0].set_value(QUESTION).run()
    assert not at.exception, at.exception
    errors = [e.value for e in at.main.error]
    assert any(f"API not reachable at {API}" in e and "uvicorn src.api.main:app" in e
               for e in errors)
