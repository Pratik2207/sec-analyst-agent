"""get_section tool: the full text of one Item of one 10-K, truncated. [track-a]

call(ticker: str, fiscal_year: int, item: str, max_tokens: int = 3000) -> ToolResult
Reads data/processed/sections/<accession_no>.json (Phase 2 parser output; the filing is
found via data/raw/filings/manifest.jsonl). One data item:
{"source_id": "section:<accession_no>:<item>", "ticker", "fiscal_year", "item", "text",
 "truncated": bool}. Filings parsed as the whole-document fallback (item "full") have no
Items: return ok=False with an error telling the agent to use search_filings instead.
"""

from src.tools.types import ToolResult

SPEC: dict = {}


def call(ticker: str, fiscal_year: int, item: str, max_tokens: int = 3000) -> ToolResult:
    raise NotImplementedError("track-a")
