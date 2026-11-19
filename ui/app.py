"""Streamlit chat UI (FR-15, FR-19). [track-a]

Run: uv run streamlit run ui/app.py   (API at settings.api_url, default http://localhost:8000)
Chat history; each answer streams its agent steps live from POST /ask/stream (SSE, see
src/api/stream.py for the event format), then shows the answer, a sources panel with
clickable EDGAR links, and an expandable trace (steps, tokens, latency).
"""

raise NotImplementedError("track-a")
