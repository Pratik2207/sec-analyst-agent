"""Router (FR-18): simple single-fact number questions go to the fast path; everything
else goes to the agent. [track-c]

route(question: str) -> Route

Plain code first (PRD 5.1): company, year and multi-hop signals are detected with regexes.
Only a question that names exactly one company and one fiscal year, with no comparison or
explanation words, reaches the small LLM, which picks the metric (structured output with
enums, thinking off). The LLM's ticker and year must agree with the ones found in code.
"""

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal

import ollama

from config.settings import get_settings, load_companies, load_metric_map
from src.api.schemas import Tokens

KEEP_ALIVE = "5m"   # Ollama's default; tests lower it to free memory sooner


@dataclass(frozen=True)
class FactQuery:
    """One company, one metric, one fiscal year."""
    ticker: str
    metric: str          # canonical metric from config/metric_map.yaml
    fiscal_year: int


@dataclass
class Route:
    kind: Literal["fast", "agent"]
    query: FactQuery | None = None        # set when kind == "fast"
    reason: str = ""                      # short explanation for the trace
    tokens: Tokens = field(default_factory=Tokens)   # LLM tokens spent on routing


# Short names people use that differ from the companies.yaml name.
_ALIASES = {
    "JPM": ["JPMorgan", "JP Morgan", "J.P. Morgan"],
    "BAC": ["BofA"],
    "GS": ["Goldman"],
    "WFC": ["Wells"],
    "C": ["Citi"],
    "USB": ["US Bancorp"],
    "TFC": ["Truist"],
    "BNY": ["Mellon"],
    "SCHW": ["Schwab"],
    "FITB": ["Fifth Third"],
    "LLY": ["Lilly"],
    "JNJ": ["J&J", "Johnson and Johnson"],
    "BMY": ["Bristol Myers", "Bristol-Myers", "BMS"],
    "GILD": ["Gilead"],
    "VRTX": ["Vertex"],
    "ON": ["ON Semiconductor", "ON Semi"],
    "NXPI": ["NXP"],
    "MCHP": ["Microchip"],
    "MPWR": ["Monolithic Power"],
    "TXN": ["TI"],
    "ADI": ["Analog Devices"],
    "ELAN": ["Elanco"],
}

# Multi-hop, comparison or explanation signals: these go straight to the agent.
_AGENT_WORDS = re.compile(
    r"\b(why|explain\w*|compar\w*|vs\.?|versus|which|who|rank\w*|highest|lowest|largest|"
    r"smallest|biggest|most|least|top|trend\w*|chang\w*|grow\w*|grew|increas\w*|"
    r"decreas\w*|declin\w*|fell|fall\w*|rise|rose|raised?|ratio\w*|share of|margins?|"
    r"percent\w*|between|both|each|all|average\w*|total of|sum|combined|over time|since|"
    r"per[ -]share|eps)\b"
    r"|%",
    re.IGNORECASE,
)
# Sector / peer-group words ("chip companies", "banks", "pharma names").
_SECTOR_WORDS = re.compile(
    r"\b(chip\w*|semiconductors?|semis|banks?|banking|lenders?|pharma\w*|drug\s*makers?|"
    r"biotechs?|sectors?|industry|industries|peers?|companies)\b",
    re.IGNORECASE,
)
# Metric words, used only to send two-metric questions to the agent.
_METRIC_WORDS = {
    "revenue": r"revenues?|sales|top line",
    "gross_profit": r"gross profit",
    "rd_expense": r"r\s*&\s*d|research and development",
    "operating_income": r"operating (?:income|profit|loss)",
    "net_income": r"net (?:income|profit|loss|earnings)",
    "total_assets": r"total assets",
}
_YEAR = re.compile(r"(?<!\d)(20\d{2})(?!\d)|\bFY\s?'?(\d{2})\b", re.IGNORECASE)


@lru_cache
def _companies() -> list[dict]:
    return load_companies()


@lru_cache
def _name_patterns() -> list[tuple[str, re.Pattern]]:
    """(ticker, pattern) pairs. Tickers match case-sensitively as whole words (so "on" or
    "key" in a sentence is not ON or KEY); names and aliases match case-insensitively."""
    pats = []
    for c in _companies():
        t = c["ticker"]
        pats.append((t, re.compile(rf"(?<![\w.]){re.escape(t)}(?![\w&])")))
        names = [c["name"], *_ALIASES.get(t, [])]
        alt = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
        pats.append((t, re.compile(rf"(?<!\w)(?:{alt})(?!\w)", re.IGNORECASE)))
    return pats


def find_companies(question: str) -> list[str]:
    """Tickers mentioned in the question, in first-mention order."""
    hits = []
    for t, pat in _name_patterns():
        m = pat.search(question)
        if m:
            hits.append((m.start(), t))
    return list(dict.fromkeys(t for _, t in sorted(hits)))


def _strip_companies(question: str) -> str:
    """The question with company names removed, so "NXP Semiconductors" is not a sector word."""
    for _, pat in _name_patterns():
        question = pat.sub(" ", question)
    return question


def find_years(question: str) -> list[int]:
    """Distinct fiscal years: "FY2024", "FY 2024", "FY24", "fiscal 2024", "2024"."""
    years = []
    for m in _YEAR.finditer(question):
        y = int(m.group(1)) if m.group(1) else 2000 + int(m.group(2))
        if y not in years:
            years.append(y)
    return years


def rule_check(question: str) -> tuple[str | None, list[str], list[int]]:
    """Plain-code routing. Returns (agent_reason or None, tickers, years)."""
    tickers, years = find_companies(question), find_years(question)
    rest = _strip_companies(question)
    if len(tickers) > 1:
        return f"several companies: {', '.join(tickers)}", tickers, years
    if not tickers:
        return "no known company named", tickers, years
    if len(years) > 1:
        return f"several fiscal years: {', '.join(map(str, years))}", tickers, years
    if not years:
        return "no fiscal year given", tickers, years
    if m := _AGENT_WORDS.search(rest):
        return f"multi-hop or explanation signal: {m.group(0)!r}", tickers, years
    if m := _SECTOR_WORDS.search(rest):
        return f"sector signal: {m.group(0)!r}", tickers, years
    metrics = [k for k, p in _METRIC_WORDS.items() if re.search(rf"\b(?:{p})\b", rest, re.I)]
    if len(metrics) > 1:
        return f"several metrics: {', '.join(metrics)}", tickers, years
    return None, tickers, years


def extract(question: str) -> tuple[dict, Tokens]:
    """Ask the fast model for {ticker, metric, fiscal_year} as structured output."""
    companies = _companies()
    metrics = list(load_metric_map()["metrics"])
    schema = {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "enum": [c["ticker"] for c in companies] + ["NONE"]},
            "metric": {"type": "string", "enum": [*metrics, "NONE"]},
            "fiscal_year": {"type": "integer"},
        },
        "required": ["ticker", "metric", "fiscal_year"],
    }
    names = ", ".join(f"{c['ticker']}={c['name']}" for c in companies)
    prompt = (
        "Extract the company, financial metric and fiscal year from the question.\n"
        f"Companies: {names}. Use NONE if the company is not listed.\n"
        f"Metrics: {', '.join(metrics)} (rd_expense = research and development; "
        "revenue = sales; net_income = profit or loss). "
        "Use NONE if the question asks for anything else (text, risks, a ratio, a margin, "
        "per-share data, cash flow, debt, guidance).\n"
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
        keep_alive=KEEP_ALIVE,
    )
    tokens = Tokens(prompt=resp.prompt_eval_count or 0, completion=resp.eval_count or 0)
    return json.loads(resp.message.content), tokens


def route(question: str) -> Route:
    reason, tickers, years = rule_check(question)
    if reason:
        return Route(kind="agent", reason=reason)
    try:
        q, tokens = extract(question)
    except (ollama.ResponseError, json.JSONDecodeError, ConnectionError) as e:
        return Route(kind="agent", reason=f"extraction failed: {type(e).__name__}")
    ticker, metric, year = q.get("ticker"), q.get("metric"), q.get("fiscal_year")
    if metric not in load_metric_map()["metrics"]:
        return Route(kind="agent", reason=f"no single stored metric (got {metric!r})",
                     tokens=tokens)
    if ticker != tickers[0] or year != years[0]:
        return Route(kind="agent", tokens=tokens,
                     reason=f"extraction {ticker}/{year} disagrees with {tickers[0]}/{years[0]}")
    return Route(kind="fast", query=FactQuery(ticker, metric, year), tokens=tokens,
                 reason=f"single fact: {ticker} {metric} FY{year}")
