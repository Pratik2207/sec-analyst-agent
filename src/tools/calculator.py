"""calculate tool: arithmetic on named values in a restricted AST evaluator (FR-9). [track-a]

call(expression: str, values: dict[str, float]) -> ToolResult
Allowed: numbers, the names in `values`, + - * / // % **, unary +/-, parentheses,
and abs/round/min/max. Everything else (imports, attribute access, other calls,
subscripts, __names, unknown names, lambdas, comprehensions) is rejected.
One data item: {"source_id": "calc:<n>", "expression", "values", "result"}.
"""

from src.tools.types import ToolResult

SPEC: dict = {}


def call(expression: str, values: dict[str, float]) -> ToolResult:
    raise NotImplementedError("track-a")
