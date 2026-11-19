"""Grader (FR-10): is a step's result good enough? If not, how to rewrite it. [track-a]

grade(step: PlanStep, result: ToolResult) -> tuple[Grade, Tokens]
Code checks first (tool error, no rows, missing tickers/years for sql_query); for
search_filings, settings.grader_model (think off) judges which chunks are relevant to
step.goal and may propose a rewritten query. Prompt in src/agent/prompts/grade.md.
"""

from dataclasses import dataclass

from src.agent.state import PlanStep
from src.api.schemas import Tokens
from src.tools.types import ToolResult


@dataclass
class Grade:
    ok: bool
    reason: str = ""
    retry_step: PlanStep | None = None   # rewritten step to try instead (None: move on)


def grade(step: PlanStep, result: ToolResult) -> tuple[Grade, Tokens]:
    raise NotImplementedError("track-a")
