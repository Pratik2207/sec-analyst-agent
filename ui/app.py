"""Streamlit chat UI (FR-15, FR-19). [track-a]

Run: uv run streamlit run ui/app.py   (API at settings.api_url, default http://localhost:8000)
Chat history; each answer streams its agent steps live from POST /ask/stream (SSE, see
src/api/stream.py for the event format), then shows the answer, a sources panel with
clickable EDGAR links, and an expandable trace (steps, tokens, latency).
"""

import sys
from pathlib import Path

# `streamlit run` puts ui/ on sys.path, not the repo root (the project is not installed).
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import streamlit as st  # noqa: E402

from config.settings import get_settings, load_companies  # noqa: E402
from ui import client  # noqa: E402
from ui.render import citation_markdown, format_answer, step_label  # noqa: E402

EXAMPLES = [
    "What was Intel's R&D expense in FY2024?",
    "Which semiconductor companies raised R&D as a share of revenue while gross margin fell, "
    "FY2024 to FY2025?",
    "What drove the increase in NVIDIA's gross margin in fiscal 2024?",
    "What was NVIDIA's revenue in FY2030?",
]


def _queue(question: str) -> None:
    st.session_state.pending = question


def sidebar(api_url: str) -> None:
    with st.sidebar:
        st.header("SEC Filings Analyst")
        err = client.health(api_url)
        if err is None:
            st.success(f"API ok at {api_url}")
        else:
            st.error(f"API {err}; {client.START_HINT}")
        st.subheader("About")
        pilots = ", ".join(f"{c['name']} ({c['ticker']})" for c in load_companies(pilot_only=True))
        st.markdown("Answers questions about SEC 10-K filings (FY2023-2025) with local models "
                    "only (Ollama + Hugging Face): XBRL facts in Postgres, filing text in "
                    "Qdrant, a LangGraph agent that plans, calls tools and cites every claim.")
        st.markdown(f"**Pilot companies:** {pilots}")
        st.subheader("Example questions")
        for i, q in enumerate(EXAMPLES):
            st.button(q, key=f"example-{i}", on_click=_queue, args=(q,),
                      width="stretch")


def show_response(resp: dict) -> None:
    """Answer, sources panel and expandable trace for one AskResponse."""
    st.markdown(format_answer(resp.get("answer", "")))
    citations = resp.get("citations") or []
    if citations:
        st.markdown("**Sources**")
        for n, c in enumerate(citations, 1):
            st.markdown(citation_markdown(n, c))
    with st.expander("Agent trace"):
        for i, step in enumerate(resp.get("steps") or [], 1):
            label, ok = step_label(step)
            st.markdown(f"**{i}. {step.get('name')}**: {label if ok else f':red[{label}]'}")
            st.json(step.get("detail") or {}, expanded=False)
        tokens = resp.get("tokens") or {}
        st.markdown(f"**Tokens:** prompt {tokens.get('prompt', 0)}, completion "
                    f"{tokens.get('completion', 0)}  \n**Latency:** "
                    f"{resp.get('latency_ms', 0)} ms")


def show_message(msg: dict) -> None:
    if msg.get("error"):
        st.error(msg["error"])
    else:
        show_response(msg["response"])


def answer_live(api_url: str, question: str) -> dict:
    """Stream one answer into the open chat message; return the history entry."""
    status = st.status("Asking the analyst...", expanded=True)

    def on_step(step: dict) -> None:
        label, ok = step_label(step)
        status.markdown(label if ok else f":red[{label}]")
        status.update(label=label)

    try:
        resp = client.ask(api_url, question, on_step)
    except client.ApiError as e:
        status.update(label="Failed", state="error", expanded=False)
        msg = {"role": "assistant", "error": str(e)}
    else:
        status.update(label=f"Done in {resp.get('latency_ms', 0) / 1000:.1f} s",
                      state="complete", expanded=False)
        msg = {"role": "assistant", "response": resp}
    show_message(msg)
    return msg


def main() -> None:
    st.set_page_config(page_title="SEC Filings Analyst", layout="wide")
    api_url = get_settings().api_url.rstrip("/")
    st.session_state.setdefault("history", [])
    sidebar(api_url)

    st.title("SEC Filings Analyst")
    st.caption("Answers come only from 10-K filings and cite their sources. "
               "Not investment advice.")
    for msg in st.session_state.history:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.markdown(msg["content"].replace("$", r"\$"))
            else:
                show_message(msg)

    question = st.chat_input("Ask about a company's 10-K filings")
    question = question or st.session_state.pop("pending", None)
    if not question:
        return
    # Append the question and a placeholder answer together, then replace the placeholder:
    # a rerun (another question, an example click) interrupts the 20-110 s stream, and the
    # question must not be left in the history without an answer (Phase 6 review).
    st.session_state.history += [
        {"role": "user", "content": question},
        {"role": "assistant", "error": "Interrupted before the answer arrived; ask again."}]
    slot = len(st.session_state.history) - 1
    with st.chat_message("user"):
        st.markdown(question.replace("$", r"\$"))
    with st.chat_message("assistant"):
        st.session_state.history[slot] = answer_live(api_url, question)


main()
