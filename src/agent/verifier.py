"""Verifier (FR-13): code only, no LLM. [track-b]

verify(draft: Draft, tool_results: list[ToolResult]) -> VerifyResult
A claim passes when every number it states (Claim.numbers) matches, via
evidence.number_matches, a number in at least one of its cited sources (fact values,
calc results, numbers in cited chunk/section text; a calc id also counts its input
facts). Claims citing unknown ids fail. Reasons are short and specific so they can be fed
back to the answer writer.
"""

from src.agent.state import Draft, VerifyResult
from src.tools.types import ToolResult


def verify(draft: Draft, tool_results: list[ToolResult]) -> VerifyResult:
    raise NotImplementedError("track-b")
