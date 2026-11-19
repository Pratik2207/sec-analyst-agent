"""list_companies tool: resolve "chip companies" etc. to tickers. [track-a]

call(sector: str | None = None) -> ToolResult
One data item per company that has data loaded: {"source_id": "companies", "ticker",
"name", "sector", "fy_end_month", "metrics": [metrics this sector reports]}.
"""

from config.settings import load_companies, load_metric_map
from src.tools import sql_tool
from src.tools.types import Source, ToolResult, tool_spec

SECTORS = sorted({c["sector"] for c in load_companies()})

# The companies table only holds companies whose XBRL facts were loaded.
_SQL = "SELECT ticker, name, sector, fy_end_month FROM companies ORDER BY ticker"

SPEC = tool_spec(
    "list_companies",
    "List the companies with loaded data: ticker, name, sector, fiscal year end month and "
    "the metrics their sector reports. Use it to turn words like \"chip companies\" or "
    "\"banks\" into tickers.",
    {"sector": {"type": "string", "enum": SECTORS,
                "description": "only this sector; omit for all"}},
    [],
)


def call(sector: str | None = None) -> ToolResult:
    if sector is not None:
        sector = str(sector).strip().lower()
        if sector not in SECTORS:
            return ToolResult.fail(f"unknown sector {sector!r}; valid: {', '.join(SECTORS)}")
    res = sql_tool.run(_SQL)
    if not res["ok"]:
        return ToolResult.fail(res["error"])
    sector_metrics = load_metric_map()["sectors"]
    data = [{"source_id": "companies", **r, "metrics": list(sector_metrics.get(r["sector"], []))}
            for r in res["rows"] if sector is None or r["sector"] == sector]
    return ToolResult(ok=True, data=data,
                      sources=[Source(source_id="companies", kind="companies")])
