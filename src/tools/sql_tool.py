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

from config.settings import get_settings

MAX_ROWS = 200

DESCRIPTION = """Run ONE read-only PostgreSQL SELECT. Tables:
companies(ticker, cik, name, sector, fy_end_month)
financial_facts(ticker, fiscal_year, period_end, metric, value, unit, xbrl_tag, accession_no)
  metric is one of: revenue, gross_profit, rd_expense, operating_income, net_income, total_assets
  Banks have no gross_profit, rd_expense or operating_income.
Always SELECT accession_no from financial_facts so results can be cited. Do math with the
calculate tool, not in SQL.
Example: SELECT ticker, fiscal_year, value, accession_no FROM financial_facts
  WHERE metric = 'rd_expense' AND ticker = 'INTC' AND fiscal_year = 2024"""

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
