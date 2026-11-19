"""sql_query tool (FR-8): read-only SELECTs against PostgreSQL as the agent_reader role.

Three layers of protection:
1. The SQL is parsed (sqlglot) and must be exactly one SELECT with no data-modifying parts.
2. The session is opened read-only.
3. The agent_reader role itself is SELECT-only, read-only by default, with a 5 s timeout.
"""

from datetime import date
from decimal import Decimal

import psycopg
import sqlglot
from sqlglot import exp

from config.settings import get_settings, load_metric_map
from src.tools.types import Source, ToolResult, edgar_index_url, tool_spec

MAX_ROWS = 200


def _build_description() -> str:
    """Tool description for the agent; metric and sector lists come from metric_map.yaml (X-2)."""
    mm = load_metric_map()
    metrics = list(mm["metrics"])
    sector_lines = "\n".join(
        f"  Sector {sector} reports: {', '.join(m for m in metrics if m in expected)}"
        + (f" (no {', '.join(m for m in metrics if m not in expected)})"
           if set(metrics) - set(expected) else "")
        for sector, expected in mm["sectors"].items()
    )
    return f"""Run ONE read-only PostgreSQL SELECT. Tables:
companies(ticker, cik, name, sector, fy_end_month)
financial_facts(ticker, fiscal_year, period_end, metric, value, unit, xbrl_tag, accession_no)
  metric is one of: {', '.join(metrics)}
{sector_lines}
Always SELECT accession_no from financial_facts so results can be cited. Do math with the
calculate tool, not in SQL.
Example: SELECT ticker, fiscal_year, value, accession_no FROM financial_facts
  WHERE metric = 'rd_expense' AND ticker = 'INTC' AND fiscal_year = 2024"""


DESCRIPTION = _build_description()

_FORBIDDEN = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop, exp.Alter,
              exp.Command, exp.Into, exp.Lock, exp.Set, exp.Transaction, exp.Commit,
              exp.Rollback)


class SqlRejected(ValueError):
    pass


def check_select(sql: str) -> None:
    """Raise SqlRejected unless `sql` is a single read-only SELECT."""
    try:
        statements = [s for s in sqlglot.parse(sql, dialect="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise SqlRejected(f"could not parse SQL: {e}") from e
    if len(statements) != 1:
        raise SqlRejected("exactly one statement is allowed")
    stmt = statements[0]
    if not isinstance(stmt, exp.Query):
        raise SqlRejected("only SELECT statements are allowed")
    for node in stmt.walk():
        if isinstance(node, _FORBIDDEN):
            raise SqlRejected(f"{type(node).__name__} is not allowed")


def _reads_facts(sql: str) -> bool:
    stmt = sqlglot.parse_one(sql, dialect="postgres")
    return any(t.name == "financial_facts" for t in stmt.find_all(exp.Table))


def _json_value(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def run(sql: str, params: tuple | dict | None = None, max_rows: int = MAX_ROWS,
        url: str | None = None) -> dict:
    """Execute a SELECT. Returns {ok, columns, rows, truncated, error}."""
    try:
        check_select(sql)
    except SqlRejected as e:
        return {"ok": False, "columns": [], "rows": [], "truncated": False, "error": str(e)}
    try:
        with psycopg.connect(url or get_settings().agent_database_url) as conn:
            conn.read_only = True
            with conn.cursor() as cur:
                cur.execute(sql, params)
                columns = [d.name for d in cur.description]
                raw = cur.fetchmany(max_rows + 1)
    except psycopg.Error as e:
        return {"ok": False, "columns": [], "rows": [], "truncated": False,
                "error": f"database error: {str(e).strip().splitlines()[0]}"}
    if _reads_facts(sql) and "accession_no" not in columns:
        return {"ok": False, "columns": [], "rows": [], "truncated": False,
                "error": "include accession_no in the SELECT list so results can be cited"}
    rows = [{c: _json_value(v) for c, v in zip(columns, r, strict=True)} for r in raw[:max_rows]]
    return {"ok": True, "columns": columns, "rows": rows, "truncated": len(raw) > max_rows,
            "error": None}


# ---- agent tool entry point (Phase 3 contract: src/tools/types.py) --------------------------

SPEC = tool_spec(
    "sql_query", DESCRIPTION,
    {"sql": {"type": "string", "description": "one PostgreSQL SELECT statement"}},
    ["sql"],
)

_FILINGS_SQL = ("SELECT DISTINCT f.accession_no, f.ticker, f.fiscal_year, c.cik "
                "FROM financial_facts f JOIN companies c ON c.ticker = f.ticker "
                "WHERE f.accession_no = ANY(%s)")


def call(sql: str) -> ToolResult:
    """Run the agent's SELECT. Each row with an accession_no gets source_id
    "xbrl:<accession_no>"; sources describe those filings (Item 8 XBRL data)."""
    res = run(sql)
    if not res["ok"]:
        return ToolResult.fail(res["error"])
    accns = sorted({r["accession_no"] for r in res["rows"] if r.get("accession_no")})
    sources: list[Source] = []
    if accns:
        filings = run(_FILINGS_SQL, (accns,))
        if not filings["ok"]:
            return ToolResult.fail(f"could not resolve filing sources: {filings['error']}")
        for f in filings["rows"]:
            sources.append(Source(
                source_id=f"xbrl:{f['accession_no']}", kind="xbrl", ticker=f["ticker"],
                form="10-K", fiscal_year=f["fiscal_year"],
                section="Item 8 Financial Statements (XBRL)",
                url=edgar_index_url(f["cik"], f["accession_no"]),
                accession_no=f["accession_no"]))
    cited = {s.source_id for s in sources}
    data = []
    for r in res["rows"]:
        sid = f"xbrl:{r['accession_no']}" if r.get("accession_no") else "companies"
        # An accession_no that matches no loaded filing is not citable.
        data.append({**r, "source_id": sid if sid in cited else "companies"})
    if res["truncated"]:
        data.append({"note": f"truncated to {MAX_ROWS} rows", "source_id": "companies"})
    # Added last so every "companies" item above resolves (types.py contract).
    if any(d["source_id"] == "companies" for d in data):
        sources.append(Source(source_id="companies", kind="companies"))
    return ToolResult(ok=True, data=data, sources=sources)
