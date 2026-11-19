"""search_filings tool: hybrid search over 10-K text chunks. [track-a]

call(query: str, ticker: str | None = None, sector: str | None = None,
     fiscal_year: int | None = None, item: str | None = None, k: int = 8) -> ToolResult
Wraps src.retrieval.hybrid_search.hybrid_search. One data item per chunk:
{"source_id": "chunk:<point_id>", "ticker", "fiscal_year", "item", "section", "text"}.
"""

from src.tools.types import ToolResult

SPEC: dict = {}


def call(query: str, ticker: str | None = None, sector: str | None = None,
         fiscal_year: int | None = None, item: str | None = None, k: int = 8) -> ToolResult:
    raise NotImplementedError("track-a")
