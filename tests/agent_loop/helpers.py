"""Shared fixtures data for the agent-loop tests: fake sql rows, chunks and sources."""

from src.tools.types import Source, ToolResult


def accn(ticker: str, year: int) -> str:
    return f"0000000{len(ticker)}-{year % 100:02d}-{sum(map(ord, ticker)):06d}"


def xbrl_source(ticker: str, year: int) -> Source:
    a = accn(ticker, year)
    return Source(source_id=f"xbrl:{a}", kind="xbrl", ticker=ticker, form="10-K",
                  fiscal_year=year, section="Item 8 Financial Statements (XBRL)",
                  url=f"https://www.sec.gov/{a}", accession_no=a)


def sql_result(facts: dict[tuple[str, str, int], float]) -> ToolResult:
    """facts: (ticker, metric, year) -> value, as sql_tool.call would return them."""
    data, sources = [], {}
    for (t, m, y), v in facts.items():
        src = xbrl_source(t, y)
        sources[src.source_id] = src
        data.append({"ticker": t, "fiscal_year": y, "period_end": f"{y}-12-31", "metric": m,
                     "value": v, "accession_no": src.accession_no,
                     "source_id": src.source_id})
    return ToolResult(ok=True, data=data, sources=list(sources.values()))


def chunk_result(n: int, ticker: str = "AMD", year: int = 2024) -> ToolResult:
    data, sources = [], []
    for i in range(1, n + 1):
        sid = f"chunk:{ticker}-{i}"
        data.append({"source_id": sid, "ticker": ticker, "fiscal_year": year, "item": "7",
                     "section": "Gross Margin", "text": f"Passage {i} about gross margin."})
        sources.append(Source(source_id=sid, kind="chunk", ticker=ticker, form="10-K",
                              fiscal_year=year, section="Item 7 MD&A | Gross Margin",
                              url=f"https://www.sec.gov/{ticker}/{i}", accession_no="0-0-0"))
    return ToolResult(ok=True, data=data, sources=sources)


SEMIS_FACTS = {
    ("NVDA", "rd_expense", 2024): 8_675e6, ("NVDA", "revenue", 2024): 60_922e6,
    ("NVDA", "gross_profit", 2024): 44_301e6,
    ("NVDA", "rd_expense", 2025): 12_914e6, ("NVDA", "revenue", 2025): 130_497e6,
    ("NVDA", "gross_profit", 2025): 97_858e6,
    ("INTC", "rd_expense", 2024): 16_546e6, ("INTC", "revenue", 2024): 53_101e6,
    ("INTC", "gross_profit", 2024): 17_345e6,
    # INTC FY2025 has no gross_profit: skipped by a calc that needs it.
    ("INTC", "rd_expense", 2025): 13_000e6, ("INTC", "revenue", 2025): 52_000e6,
}
