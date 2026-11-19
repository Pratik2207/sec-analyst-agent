"""Fast path (FR-18): one SQL tool call + a templated answer, no planner. [track-c]

answer(question: str, r: Route) -> AskResponse
Takes over the Phase 1 skeleton logic in src/api/main.py (SQL template, answer format,
"Not found in the filings."). Citations come from sql_tool.call() sources.

The SQL goes through sql_tool.call(), the same entry point the agent uses, so the citation is
built in one place. call() takes SQL text only, so the three values are written in as
literals, but only after each is checked against a closed set: the ticker must be one of the
companies.yaml tickers (and match ^[A-Z.]{1,6}$), the metric a metric_map.yaml key, the year
an int. No text from the question ever reaches the SQL.
"""

import re
import time

from config.settings import load_companies, load_metric_map
from src.agent.router import FactQuery, Route
from src.api.schemas import AskResponse, Step
from src.observability.tracing import get_tracer
from src.tools import sql_tool

NOT_FOUND = "Not found in the filings."

_TICKER = re.compile(r"^[A-Z.]{1,6}$")
_METRIC = re.compile(r"^[a-z_]{1,40}$")


def format_usd(value: float) -> str:
    sign, value = ("-" if value < 0 else ""), abs(value)
    for size, suffix in ((1e9, "billion"), (1e6, "million")):
        if value >= size:
            return f"{sign}${value / size:,.2f} {suffix}"
    return f"{sign}${value:,.0f}"


def build_sql(q: FactQuery) -> str:
    """The fixed SELECT for one fact. Raises ValueError on any value outside the closed sets."""
    tickers = {c["ticker"] for c in load_companies()}
    if not (isinstance(q.ticker, str) and _TICKER.match(q.ticker) and q.ticker in tickers):
        raise ValueError(f"bad ticker {q.ticker!r}")
    if not (isinstance(q.metric, str) and _METRIC.match(q.metric)
            and q.metric in load_metric_map()["metrics"]):
        raise ValueError(f"bad metric {q.metric!r}")
    if type(q.fiscal_year) is not int:
        raise ValueError(f"bad fiscal year {q.fiscal_year!r}")
    return ("SELECT f.value, f.period_end, f.xbrl_tag, f.accession_no, c.name "
            "FROM financial_facts f JOIN companies c ON c.ticker = f.ticker "
            f"WHERE f.ticker = '{q.ticker}' AND f.metric = '{q.metric}' "
            f"AND f.fiscal_year = {q.fiscal_year}")


def answer(question: str, r: Route) -> AskResponse:
    start = time.perf_counter()
    if r.kind != "fast" or r.query is None:
        raise ValueError("fast_path.answer needs a fast route")
    q = r.query
    steps = [Step(name="route", detail={"kind": r.kind, "reason": r.reason,
                                        "ticker": q.ticker, "metric": q.metric,
                                        "fiscal_year": q.fiscal_year})]
    sql = build_sql(q)
    with get_tracer().span("tool:sql_query", {"sql": sql}) as sp:   # NFR-12
        res = sql_tool.call(sql)
        sp.update(output={"ok": res.ok, "items": len(res.data), "error": res.error})
    steps.append(Step(name="sql_query", detail={"sql": sql, "ok": res.ok, "rows": res.data,
                                                 "error": res.error}))

    def done(text: str, citations: list) -> AskResponse:
        return AskResponse(answer=text, citations=citations, steps=steps, tokens=r.tokens,
                           latency_ms=int((time.perf_counter() - start) * 1000))

    row = res.data[0] if res.ok and res.data else None
    source = res.source(row["source_id"]) if row else None
    citation = source.citation() if source else None
    if citation is None:   # no row, or a row that can't be cited: never return an uncited number
        return done(NOT_FOUND, [])
    label = q.metric.replace("_", " ").replace("rd ", "R&D ")
    text = (f"{row['name']}'s {label} for fiscal year {q.fiscal_year} "
            f"(period ending {row['period_end']}) was {format_usd(row['value'])}.")
    return done(text, [citation])
