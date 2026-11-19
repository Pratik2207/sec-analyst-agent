"""Router (FR-18): simple single-fact number questions go to the fast path; everything
else goes to the agent. [track-c]

route(question: str) -> Route
"""

from dataclasses import dataclass, field
from typing import Literal

from src.api.schemas import Tokens


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


def route(question: str) -> Route:
    raise NotImplementedError("track-c")
