"""POST /ask/stream: Server-Sent Events of the agent's steps as they happen (FR-19). [track-b]

Wire format (Phase 6 contract), one SSE message per event, `data: <json>\n\n`:
  {"type": "step",  "data": <Step as JSON>}          zero or more, in order
  {"type": "final", "data": <AskResponse as JSON>}   exactly one, last
  {"type": "error", "data": {"message": str}}        instead of final, if something failed
Routing as in POST /ask: fast questions emit the route + sql_query steps then final; agent
questions stream graph.run_agent_events (never send its internal "tool_results").
The whole request is one trace (observability.tracing), like POST /ask.
"""

from fastapi import APIRouter, HTTPException

from src.api.schemas import AskRequest

router = APIRouter()


@router.post("/ask/stream")
def ask_stream(req: AskRequest):
    raise HTTPException(501, "track-b")
