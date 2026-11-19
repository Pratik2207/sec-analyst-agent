"""Grader (FR-10): is a step's result good enough? If not, how to rewrite it. [track-a]

grade(step: PlanStep, result: ToolResult) -> tuple[Grade, Tokens]
Code checks first (tool error, no rows, missing tickers/years for sql_query); for
search_filings, settings.grader_model (think off) judges which chunks are relevant to
step.goal and may propose a rewritten query. Prompt in src/agent/prompts/grade.md.

Retry policy: a transient tool error (database / search failure) retries the same step; a
validation error does not (the same arguments would fail again). sql_query gaps are noted,
never retried. A search with no relevant passage retries with the grader's rewritten query.
The caller (graph) enforces MAX_RETRIES per step and keeps only Grade.keep_ids passages.
"""

from dataclasses import dataclass
from pathlib import Path

from config.settings import get_settings
from src.agent.llm import LLMError, chat_json
from src.agent.state import PlanStep
from src.api.schemas import Tokens
from src.tools.types import ToolResult

PROMPT = (Path(__file__).parent / "prompts" / "grade.md").read_text(encoding="utf-8")
PASSAGE_CHARS = 1200
# Errors worth retrying unchanged; everything else is a validation error.
TRANSIENT_ERRORS = ("database error", "search failed", "could not resolve filing sources")


@dataclass
class Grade:
    ok: bool
    reason: str = ""
    retry_step: PlanStep | None = None   # rewritten step to try instead (None: move on)
    keep_ids: list[str] | None = None    # search_filings: relevant chunk ids (None: keep all)


def _grade_sql(step: PlanStep, result: ToolResult) -> Grade:
    rows = [d for d in result.data if "metric" in d and "value" in d]
    if not rows:
        return Grade(False, "no rows: the data does not exist")
    missing = []
    have = {(r.get("ticker"), r.get("fiscal_year")) for r in rows}
    tickers = {r.get("ticker") for r in rows}
    years = {r.get("fiscal_year") for r in rows}
    missing += [f"no data for {t}" for t in step.tickers if t not in tickers]
    missing += [f"no data for FY{y}" for y in step.fiscal_years if y not in years]
    missing += [f"no data for {t} FY{y}" for t in step.tickers if t in tickers
                for y in step.fiscal_years if y in years and (t, y) not in have]
    return Grade(True, "; ".join(missing) or f"{len(rows)} rows")


def _grade_search(step: PlanStep, result: ToolResult) -> tuple[Grade, Tokens]:
    chunks = [d for d in result.data if d.get("source_id", "").startswith("chunk:")]
    if not chunks:
        return Grade(False, "no passages matched"), Tokens()
    user = f"Goal: {step.goal}\nQuery: {step.query}\n\n{_escape_passages(chunks)}"
    schema = {"type": "object", "properties": {
        "relevant_ids": {"type": "array",
                         "items": {"type": "integer", "enum": list(range(1, len(chunks) + 1))}},
        "rewrite": {"type": "string"}}, "required": ["relevant_ids", "rewrite"]}
    try:
        out, tokens = chat_json(get_settings().grader_model, PROMPT, user, schema, think=False)
    except LLMError as e:
        return Grade(True, f"grader unavailable, kept all passages ({e})"[:300]), Tokens()
    ids = out.get("relevant_ids") if isinstance(out, dict) else None
    nums = {n for n in ids if isinstance(n, int) and not isinstance(n, bool)} \
        if isinstance(ids, list) else set()
    keep = [d["source_id"] for i, d in enumerate(chunks, 1) if i in nums]
    if keep:
        return Grade(True, f"{len(keep)}/{len(chunks)} passages relevant", keep_ids=keep), tokens
    rewrite = out.get("rewrite") if isinstance(out, dict) else None
    rewrite = rewrite.strip() if isinstance(rewrite, str) else ""
    if rewrite and rewrite.lower() != (step.query or "").strip().lower():
        return Grade(False, f"no relevant passages; rewrite: {rewrite}", keep_ids=[],
                     retry_step=step.model_copy(update={"query": rewrite})), tokens
    return Grade(False, "no relevant passages", keep_ids=[]), tokens


def _escape_passages(chunks: list[dict]) -> str:
    """Numbered passages; "<" in filing text is escaped so it cannot close a passage."""
    out = []
    for i, d in enumerate(chunks, 1):
        head = (f'{d.get("ticker", "")} FY{d.get("fiscal_year", "")} Item {d.get("item", "")} '
                f'{d.get("section", "")}')
        body = f"{head}: {str(d.get('text', ''))[:PASSAGE_CHARS]}".replace("<", "&lt;")
        out.append(f'<passage n="{i}">{body}</passage>')
    return "\n".join(out)


def grade(step: PlanStep, result: ToolResult) -> tuple[Grade, Tokens]:
    if not result.ok:
        err = result.error or "unknown error"
        if err.lower().startswith(TRANSIENT_ERRORS):
            return Grade(False, f"tool error, retrying: {err}", retry_step=step), Tokens()
        return Grade(False, f"tool error: {err}"), Tokens()
    if step.tool == "sql_query":
        return _grade_sql(step, result), Tokens()
    if step.tool == "search_filings":
        return _grade_search(step, result)
    if not result.data:
        return Grade(False, "empty result"), Tokens()
    return Grade(True, f"{len(result.data)} items"), Tokens()
