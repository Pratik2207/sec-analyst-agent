"""Phase 4 interface contract: agent state and the types shared by the loop (track-a) and
the answer writer / verifier (track-b). Owned by the main session.

Flow (PRD 6.2): plan (one LLM call, the whole plan with arguments) -> for each step:
execute the tool, grade, maybe rewrite and retry (<= MAX_RETRIES per step) -> answer
(structured claims with source_ids) -> verify (code) -> one re-answer with feedback if a
claim fails -> render. Hard cap: MAX_TOOL_CALLS tool executions per question; an identical
repeated call (same tool + same arguments) also stops the loop. Either stop yields a
partial answer from whatever evidence exists.
"""

from typing import Literal, TypedDict

from pydantic import BaseModel, Field

from src.api.schemas import Step, Tokens
from src.tools.types import ToolResult

MAX_TOOL_CALLS = 8      # NFR-7
MAX_RETRIES = 2         # FR-10, per step
MAX_ANSWER_RETRIES = 1  # FR-13: failed claims go back once, then are removed and flagged

ToolName = Literal["sql_query", "search_filings", "get_section", "calculate", "list_companies"]


class PlanStep(BaseModel):
    """One step of the plan. Flat on purpose (small models fill flat JSON schemas well);
    which fields matter depends on `tool`:

    sql_query      tickers and/or sector, metrics, fiscal_years. Code builds the SELECT from
                   these (never LLM-written SQL), always selecting accession_no.
    search_filings query, plus optional single filters tickers[0], fiscal_years[0], item.
    get_section    tickers[0], fiscal_years[0], item.
    calculate      expression over variables named <metric>_<fiscal_year> (e.g.
                   "rd_expense_2025 / revenue_2025 * 100"); code evaluates it once per
                   ticker using that ticker's facts from earlier sql_query steps. `name`
                   labels the result (e.g. "rd_share_2025").
    list_companies sector (optional).
    """
    tool: ToolName
    goal: str = Field(description="what this step finds out, one short sentence")
    tickers: list[str] = []
    sector: str | None = None
    metrics: list[str] = []
    fiscal_years: list[int] = []
    query: str | None = None
    item: str | None = None
    expression: str | None = None
    name: str | None = None

    def signature(self) -> str:
        """Identity of the tool call, for repeated-call detection (NFR-7)."""
        return self.model_dump_json(exclude={"goal"})


class Claim(BaseModel):
    text: str                      # one sentence, no citation markers
    source_ids: list[str]          # ids from the evidence (xbrl:..., chunk:..., calc:..., ...)
    numbers: list[float] = []      # filled by evidence.numbers_in(text)


class Draft(BaseModel):
    claims: list[Claim] = []
    not_found: bool = False        # the evidence does not answer the question


class VerifyResult(BaseModel):
    ok_claims: list[Claim] = []
    failed_claims: list[tuple[Claim, str]] = []   # (claim, reason)


class AgentState(TypedDict, total=False):
    question: str
    plan: list[PlanStep]
    step_idx: int
    tool_results: list[ToolResult]        # every executed call, in order
    step_results: dict[int, list[int]]    # step index -> indexes into tool_results
    retries: dict[int, int]               # step index -> retries used
    tool_calls: int                       # executions so far (<= MAX_TOOL_CALLS)
    signatures: list[str]                 # PlanStep.signature() of every executed call
    draft: Draft | None
    verified: list[Claim]                 # claims that passed verify on an earlier attempt
    answer_retries: int
    feedback: str | None                  # verifier feedback for the re-answer
    flags: list[str]                      # e.g. "step cap reached", "claim removed: ..."
    stop_reason: str | None               # "done" | "tool cap" | "repeated call" | ...
    trace: list[Step]                     # becomes AskResponse.steps
    tokens: Tokens
