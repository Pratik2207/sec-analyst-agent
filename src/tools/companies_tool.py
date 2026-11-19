"""list_companies tool: resolve "chip companies" etc. to tickers. [track-a]

call(sector: str | None = None) -> ToolResult
One data item per company that has data loaded: {"source_id": "companies", "ticker",
"name", "sector", "fy_end_month", "metrics": [metrics this sector reports]}.
"""

from src.tools.types import ToolResult

SPEC: dict = {}


def call(sector: str | None = None) -> ToolResult:
    raise NotImplementedError("track-a")
