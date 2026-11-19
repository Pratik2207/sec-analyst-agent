"""FastAPI app. Phase 1 skeleton: POST /ask answers single-number questions only
(one company, one metric, one fiscal year) from financial_facts.

Run: uv run uvicorn src.api.main:app --port 8000
"""

import json
import time

import ollama
from fastapi import FastAPI

from config.settings import get_settings, load_metric_map
from src.api.schemas import AskRequest, AskResponse, Citation, Step, Tokens
from src.tools import sql_tool

NOT_FOUND = "Not found in the filings."

app = FastAPI(title="SEC Filings Analyst")


def edgar_url(cik: str, accession_no: str) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{accession_no.replace('-', '')}/{accession_no}-index.htm")


def extract_query(question: str, companies: list[dict], metrics: list[str]) -> tuple[dict, Tokens]:
    """Ask the fast model for {ticker, metric, fiscal_year} as structured output."""
    tickers = [c["ticker"] for c in companies]
    schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "enum": [*tickers, "NONE"]},
            "metric": {"type": "string", "enum": [*metrics, "NONE"]},
            "fiscal_year": {"type": "integer"},
        },
        "required": ["ticker", "metric", "fiscal_year"],
    }
    names = ", ".join(f"{c['ticker']}={c['name']}" for c in companies)
    prompt = (
        "Extract the company, financial metric and fiscal year from the question.\n"
        f"Companies: {names}. Use NONE if the company is not listed.\n"
        f"Metrics: {', '.join(metrics)} (rd_expense = research and development). "
        "Use NONE if no listed metric matches.\n"
        "fiscal_year: the 4-digit fiscal year asked about, or 0 if none.\n"
        f"Question: {question}"
    )
    s = get_settings()
    resp = ollama.Client(host=s.ollama_host).chat(
        model=s.fast_model,
        messages=[{"role": "user", "content": prompt}],
        format=schema,
        think=False,
        options={"temperature": 0},
    )
    tokens = Tokens(prompt=resp.prompt_eval_count or 0, completion=resp.eval_count or 0)
    return json.loads(resp.message.content), tokens


def format_usd(value: float) -> str:
    sign, value = ("-" if value < 0 else ""), abs(value)
    for size, suffix in ((1e9, "billion"), (1e6, "million")):
        if value >= size:
            return f"{sign}${value / size:,.2f} {suffix}"
    return f"{sign}${value:,.0f}"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    start = time.perf_counter()
    steps: list[Step] = []

    def done(answer: str, citations: list[Citation], tokens: Tokens) -> AskResponse:
        return AskResponse(answer=answer, citations=citations, steps=steps, tokens=tokens,
                           latency_ms=int((time.perf_counter() - start) * 1000))

    companies = sql_tool.run("SELECT ticker, name FROM companies ORDER BY ticker")
    metrics = list(load_metric_map()["metrics"])
    query, tokens = extract_query(req.question, companies["rows"], metrics)
    steps.append(Step(name="extract", detail=query))
    if query["ticker"] == "NONE" or query["metric"] == "NONE" or not query["fiscal_year"]:
        return done(NOT_FOUND, [], tokens)

    result = sql_tool.run(
        "SELECT f.value, f.period_end, f.xbrl_tag, f.accession_no, c.cik, c.name "
        "FROM financial_facts f JOIN companies c ON c.ticker = f.ticker "
        "WHERE f.ticker = %s AND f.metric = %s AND f.fiscal_year = %s",
        (query["ticker"], query["metric"], query["fiscal_year"]),
    )
    steps.append(Step(name="sql_query", detail={"ok": result["ok"], "rows": result["rows"],
                                                 "error": result["error"]}))
    if not result["ok"] or not result["rows"]:
        return done(NOT_FOUND, [], tokens)

    row = result["rows"][0]
    label = query["metric"].replace("_", " ").replace("rd ", "R&D ")
    answer = (f"{row['name']}'s {label} for fiscal year {query['fiscal_year']} "
              f"(period ending {row['period_end']}) was {format_usd(row['value'])}.")
    citation = Citation(
        ticker=query["ticker"], form="10-K", fiscal_year=query["fiscal_year"],
        section=f"Item 8 Financial Statements (XBRL {row['xbrl_tag']})",
        accession_no=row["accession_no"], url=edgar_url(row["cik"], row["accession_no"]),
    )
    return done(answer, [citation], tokens)
