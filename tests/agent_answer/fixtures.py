"""Realistic ToolResults for the answer writer and verifier tests.

Shapes follow the Phase 3 tools: sql_query fact rows (source_id xbrl:<accession_no>),
calculate items (calc:<n>, with input_source_ids), search_filings chunks (chunk:<id>).
Values are in USD; NVDA/AMD/QCOM FY2024 and NVDA FY2025 follow the filings, the rest are
illustrative (INTC FY2025 is set so that exactly one company qualifies in the multi-hop
question).
"""

from src.tools.types import Source, ToolResult, edgar_index_url

M = 1e6
CIK = {"NVDA": "0001045810", "AMD": "0000002488", "INTC": "0000050863", "QCOM": "0000804328"}
# ticker -> fiscal_year -> (accession_no, period_end, revenue, rd_expense, gross_profit)
FILINGS = {
    "NVDA": {2024: ("0001045810-24-000029", "2024-01-28", 60_922 * M, 8_675 * M, 44_301 * M),
             2025: ("0001045810-25-000023", "2025-01-26", 130_497 * M, 12_914 * M, 97_858 * M)},
    "AMD": {2024: ("0000002488-25-000012", "2024-12-28", 25_785 * M, 6_456 * M, 12_725 * M),
            2025: ("0000002488-26-000018", "2025-12-27", 34_639 * M, 8_086 * M, 17_246 * M)},
    "INTC": {2024: ("0000050863-25-000009", "2024-12-28", 53_101 * M, 16_546 * M, 17_345 * M),
             2025: ("0000050863-26-000011", "2025-12-27", 50_200 * M, 16_900 * M, 15_800 * M)},
    "QCOM": {2024: ("0000804328-24-000088", "2024-09-29", 38_962 * M, 8_893 * M, 21_902 * M),
             2025: ("0000804328-25-000079", "2025-09-28", 44_284 * M, 9_042 * M, 24_547 * M)},
}
NVDA_FY25_XBRL = "xbrl:0001045810-25-000023"


def facts(tickers=tuple(FILINGS), years=(2024, 2025)) -> ToolResult:
    data, sources = [], []
    for t in tickers:
        for fy in years:
            acc, end, rev, rd, gp = FILINGS[t][fy]
            sid = f"xbrl:{acc}"
            for metric, v in (("revenue", rev), ("rd_expense", rd), ("gross_profit", gp)):
                data.append({"ticker": t, "fiscal_year": fy, "metric": metric, "value": v,
                             "period_end": end, "accession_no": acc, "source_id": sid})
            sources.append(Source(source_id=sid, kind="xbrl", ticker=t, form="10-K",
                                  fiscal_year=fy, section="Item 8 Financial Statements (XBRL)",
                                  url=edgar_index_url(CIK[t], acc), accession_no=acc))
    return ToolResult(ok=True, data=data, sources=sources)


def calcs(tickers=tuple(FILINGS), start: int = 1) -> ToolResult:
    """Per ticker: rd_share_<fy> and gross_margin_<fy> (in %) for FY2024 and FY2025."""
    data, sources = [], []
    n = start
    for t in tickers:
        for fy in (2024, 2025):
            acc, _, rev, rd, gp = FILINGS[t][fy]
            for name, expr, num, var in (
                    (f"rd_share_{fy}", f"rd_expense_{fy} / revenue_{fy} * 100", rd, "rd_expense"),
                    (f"gross_margin_{fy}", f"gross_profit_{fy} / revenue_{fy} * 100", gp,
                     "gross_profit")):
                sid = f"calc:{n}"
                data.append({"source_id": sid, "ticker": t, "name": name, "expression": expr,
                             "values": {f"{var}_{fy}": num, f"revenue_{fy}": rev},
                             "result": num / rev * 100, "input_source_ids": [f"xbrl:{acc}"]})
                sources.append(Source(source_id=sid, kind="calc"))
                n += 1
    return ToolResult(ok=True, data=data, sources=sources)


NVDA_GM_CHUNK = ToolResult(ok=True, data=[{
    "source_id": "chunk:7f1c2e9a", "ticker": "NVDA", "fiscal_year": 2025, "item": "7",
    "section": "Gross Margin",
    "text": "Gross margin increased to 75.0% in fiscal year 2025 from 72.7% a year ago, "
            "primarily driven by a higher mix of Data Center revenue. Inventory provisions "
            "totaled $3.7 billion in fiscal year 2025, compared with $1.4 billion in fiscal "
            "year 2024."}],
    sources=[Source(source_id="chunk:7f1c2e9a", kind="chunk", ticker="NVDA", form="10-K",
                    fiscal_year=2025, section="Item 7 MD&A | Gross Margin",
                    url="https://www.sec.gov/Archives/edgar/data/1045810/000104581025000023/"
                        "nvda-20250126.htm",
                    accession_no="0001045810-25-000023")])

MULTIHOP_QUESTION = ("Which semiconductor companies raised R&D as a share of revenue while "
                     "gross margin fell, FY2024 to FY2025?")


def multihop() -> list[ToolResult]:
    return [facts(), calcs()]
