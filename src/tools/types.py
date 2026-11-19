"""Phase 3 interface contract: what every agent tool returns. Owned by the main session.

Every tool module exposes:
    SPEC: dict            # Ollama tool-calling schema: {"type": "function", "function": {...}}
    call(**kwargs) -> ToolResult   # the agent-facing entry point

Every item in ToolResult.data carries a "source_id" key that matches one Source in
ToolResult.sources. Filing sources (kind xbrl/chunk/section) turn into a Citation via
Source.citation(); calc and companies sources are not filing citations.
"""

from typing import Literal

from pydantic import BaseModel

from src.api.schemas import Citation

SourceKind = Literal["xbrl", "chunk", "section", "calc", "companies"]


def edgar_index_url(cik: str | int, accession_no: str) -> str:
    """The filing's EDGAR index page."""
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession_no.replace('-', '')}/{accession_no}-index.htm")


class Source(BaseModel):
    source_id: str            # xbrl:<accession_no> | chunk:<point_id> |
                              # section:<accession_no>:<item> | calc:<n> | companies
    kind: SourceKind
    ticker: str | None = None
    form: str | None = None   # "10-K"
    fiscal_year: int | None = None
    section: str | None = None   # e.g. "Item 7 MD&A | Gross Margin", "Item 8 (XBRL)"
    url: str | None = None
    accession_no: str | None = None

    def citation(self) -> Citation | None:
        if self.kind not in ("xbrl", "chunk", "section"):
            return None
        return Citation(ticker=self.ticker, form=self.form or "10-K",
                        fiscal_year=self.fiscal_year, section=self.section or "",
                        accession_no=self.accession_no, url=self.url)


class ToolResult(BaseModel):
    ok: bool
    data: list[dict] = []
    sources: list[Source] = []
    error: str | None = None

    @classmethod
    def fail(cls, error: str) -> "ToolResult":
        return cls(ok=False, error=error)

    def source(self, source_id: str) -> Source | None:
        return next((s for s in self.sources if s.source_id == source_id), None)


def tool_spec(name: str, description: str, properties: dict, required: list[str]) -> dict:
    """Ollama/OpenAI-style function schema."""
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }}
