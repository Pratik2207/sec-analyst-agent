"""Planner (FR-7): one structured-output LLM call turns the question into list[PlanStep]
with all tool arguments filled in. [track-a]

plan(question: str) -> tuple[list[PlanStep], Tokens]
Model: settings.planner_model (think=settings.planner_think), via llm.chat_json.
Prompt in src/agent/prompts/plan.md. Validate/normalise every step in code (enums for
tickers, sectors, metrics, items; years as ints; drop invalid steps) and cap the plan at
MAX_TOOL_CALLS steps.
"""

from src.agent.state import PlanStep
from src.api.schemas import Tokens


def plan(question: str) -> tuple[list[PlanStep], Tokens]:
    raise NotImplementedError("track-a")
