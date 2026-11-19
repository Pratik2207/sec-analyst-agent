"""Planner (FR-7): one structured-output LLM call turns the question into list[PlanStep]
with all tool arguments filled in. [track-a]

plan(question: str) -> tuple[list[PlanStep], Tokens]
Model: settings.planner_model (think=settings.planner_think), via llm.chat_json.
Prompt in src/agent/prompts/plan.md. Validate/normalise every step in code (enums for
tickers, sectors, metrics, items; years as ints; drop invalid steps) and cap the plan at
MAX_TOOL_CALLS steps.

If the LLM fails, or no step survives validation, the plan is one search_filings step over
the question (FALLBACK).
"""

import ast
from pathlib import Path
from typing import get_args

from config.settings import get_settings, load_companies, load_metric_map
from src.agent.llm import LLMError, chat_json
from src.agent.state import MAX_TOOL_CALLS, PlanStep, ToolName
from src.api.schemas import Tokens
from src.ingest.chunk_schema import TEXT_ITEMS

TOOLS = list(get_args(ToolName))
TICKERS = [c["ticker"] for c in load_companies()]
SECTORS = sorted({c["sector"] for c in load_companies()})
METRICS = list(load_metric_map()["metrics"])
ITEMS = list(TEXT_ITEMS)
CALC_FUNCS = {"abs", "round", "min", "max"}
MIN_YEAR, MAX_YEAR = 1990, 2100

_PROMPT_PATH = Path(__file__).parent / "prompts" / "plan.md"

SCHEMA = {
    "type": "object",
    "properties": {"steps": {
        "type": "array", "minItems": 1, "maxItems": MAX_TOOL_CALLS,
        "items": {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": TOOLS},
                "goal": {"type": "string"},
                "tickers": {"type": "array", "items": {"type": "string", "enum": TICKERS}},
                "sector": {"type": "string", "enum": SECTORS},
                "metrics": {"type": "array", "items": {"type": "string", "enum": METRICS}},
                "fiscal_years": {"type": "array", "items": {"type": "integer"}},
                "query": {"type": "string"},
                "item": {"type": "string", "enum": ITEMS},
                "expression": {"type": "string"},
                "name": {"type": "string"},
            },
            "required": ["tool", "goal"],
        },
    }},
    "required": ["steps"],
}


def system_prompt() -> str:
    companies = "\n".join(f"  {c['ticker']}: {c['name']} ({c['sector']})"
                          for c in load_companies())
    sectors = load_metric_map()["sectors"]
    sector_metrics = "\n".join(
        f"  {s}: {', '.join(ms)}"
        + (f" (NO {', '.join(m for m in METRICS if m not in ms)})"
           if set(METRICS) - set(ms) else "")
        for s, ms in sectors.items())
    return (_PROMPT_PATH.read_text(encoding="utf-8")
            .replace("{companies}", companies)
            .replace("{sector_metrics}", sector_metrics)
            .replace("{max_steps}", str(MAX_TOOL_CALLS)))


def fallback_plan(question: str) -> list[PlanStep]:
    return [PlanStep(tool="search_filings", goal="find passages that answer the question",
                     query=question)]


# ---- validation ------------------------------------------------------------------------

def _as_year(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    elif isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, int) and MIN_YEAR <= v <= MAX_YEAR:
        return v
    return None


def _str_list(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _unique(xs: list) -> list:
    return list(dict.fromkeys(xs))


def _opt_str(v) -> str | None:
    return v.strip() or None if isinstance(v, str) else None


def split_var(name: str) -> tuple[str, int] | None:
    """'rd_expense_2025' -> ('rd_expense', 2025); None if it is not <metric>_<year>."""
    base, _, year = name.rpartition("_")
    if base in METRICS and len(year) == 4 and year.isdigit():
        return base, int(year)
    return None


def expression_names(expression: str) -> set[str] | None:
    """Variable names used in a calculate expression (None if it does not parse)."""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return None
    return {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} - CALC_FUNCS


def _fetched(name: str, earlier: list[PlanStep]) -> bool:
    mv = split_var(name)
    if mv is None:
        return False
    metric, year = mv
    return any(s.tool == "sql_query" and metric in s.metrics
               and (not s.fiscal_years or year in s.fiscal_years) for s in earlier)


def normalise_step(raw, earlier: list[PlanStep]) -> list[PlanStep]:
    """Zero or more valid steps for one raw step from the LLM. A search_filings or
    get_section step over several tickers becomes one step per ticker."""
    if not isinstance(raw, dict) or raw.get("tool") not in TOOLS:
        return []
    tool = raw["tool"]
    goal = (_opt_str(raw.get("goal")) or tool)[:300]
    tickers = _unique([t.strip().upper() for t in _str_list(raw.get("tickers"))
                       if t.strip().upper() in TICKERS])
    sector = _opt_str(raw.get("sector"))
    sector = sector.lower() if sector and sector.lower() in SECTORS else None
    metrics = _unique([m.strip() for m in _str_list(raw.get("metrics"))
                       if m.strip() in METRICS])
    years_raw = raw.get("fiscal_years")
    years_raw = years_raw if isinstance(years_raw, list) else [years_raw]
    years = sorted({y for y in map(_as_year, years_raw) if y is not None})
    query = _opt_str(raw.get("query"))
    item = _opt_str(raw.get("item"))
    item = item.upper() if item and item.upper() in ITEMS else None
    expression = _opt_str(raw.get("expression"))
    name = _opt_str(raw.get("name"))

    if tool == "sql_query":
        if not metrics or not (tickers or sector):
            return []
        return [PlanStep(tool=tool, goal=goal, tickers=tickers, sector=sector,
                         metrics=metrics, fiscal_years=years)]
    if tool == "search_filings":
        if not query:
            return []
        # The tool filters on one year; several years means "don't filter by year".
        years = years if len(years) == 1 else []
        return [PlanStep(tool=tool, goal=goal, tickers=[t] if t else [],
                         sector=None if t else sector, fiscal_years=years, query=query,
                         item=item) for t in (tickers or [None])]
    if tool == "get_section":
        if not (tickers and years and item):
            return []
        return [PlanStep(tool=tool, goal=goal, tickers=[t], fiscal_years=years[:1], item=item)
                for t in tickers]
    if tool == "calculate":
        names = expression_names(expression) if expression else None
        if not names or not all(_fetched(n, earlier) for n in names):
            return []
        if not (name and name.isidentifier()):
            name = "result"
        return [PlanStep(tool=tool, goal=goal, tickers=tickers, expression=expression,
                         name=name)]
    return [PlanStep(tool=tool, goal=goal, sector=sector)]   # list_companies


def normalise(raw_steps) -> list[PlanStep]:
    steps: list[PlanStep] = []
    seen: set[str] = set()
    for raw in raw_steps if isinstance(raw_steps, list) else []:
        for s in normalise_step(raw, steps):
            if s.signature() not in seen:   # an identical step would only repeat a call
                seen.add(s.signature())
                steps.append(s)
    return steps[:MAX_TOOL_CALLS]


def plan(question: str) -> tuple[list[PlanStep], Tokens]:
    s = get_settings()
    try:
        out, tokens = chat_json(s.planner_model, system_prompt(), question, SCHEMA,
                                think=s.planner_think)
    except LLMError:
        return fallback_plan(question), Tokens()
    steps = normalise(out.get("steps") if isinstance(out, dict) else None)
    return (steps or fallback_plan(question)), tokens
