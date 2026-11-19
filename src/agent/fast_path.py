"""Fast path (FR-18): one SQL tool call + a templated answer, no planner. [track-c]

answer(question: str, r: Route) -> AskResponse
Takes over the Phase 1 skeleton logic in src/api/main.py (SQL template, answer format,
"Not found in the filings."). Citations come from sql_tool.call() sources.
"""

from src.agent.router import Route
from src.api.schemas import AskResponse

NOT_FOUND = "Not found in the filings."


def answer(question: str, r: Route) -> AskResponse:
    raise NotImplementedError("track-c")
