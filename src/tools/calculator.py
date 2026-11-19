"""calculate tool: arithmetic on named values in a restricted AST evaluator (FR-9). [track-a]

call(expression: str, values: dict[str, float]) -> ToolResult
Allowed: numbers, the names in `values`, + - * / // % **, unary +/-, parentheses,
and abs/round/min/max. Everything else (imports, attribute access, other calls,
subscripts, __names, unknown names, lambdas, comprehensions) is rejected.
One data item: {"source_id": "calc:<n>", "expression", "values", "result"}.

The expression is parsed with ast and walked node by node; eval/exec are never used.
All numbers are evaluated as floats, so integer powers cannot grow without bound.
"""

import ast
import itertools
import math
import operator

from src.tools.types import Source, ToolResult, tool_spec

MAX_EXPRESSION_CHARS = 500
MAX_EXPONENT = 100

_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
           ast.Pow: operator.pow}
_UNARYOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max}

_ids = itertools.count(1)

SPEC = tool_spec(
    "calculate",
    "Evaluate arithmetic on named numbers. Use it for every ratio, % change, sum or "
    "difference; never do math yourself. Allowed: + - * / // % **, parentheses, "
    "abs, round, min, max, and the names given in values.\n"
    'Example: expression "(rd / revenue) * 100", values {"rd": 8675, "revenue": 60922}',
    {"expression": {"type": "string",
                    "description": "arithmetic using only the names in values"},
     "values": {"type": "object", "additionalProperties": {"type": "number"},
                "description": "name -> number, e.g. {\"rd\": 8675}"}},
    ["expression", "values"],
)


class CalcError(ValueError):
    pass


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _eval(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant):
        if not _is_number(node.value):
            raise CalcError(f"only numbers are allowed, not {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in values:
            raise CalcError(f"unknown name {node.id!r}; pass it in values "
                            f"(known: {', '.join(sorted(values)) or 'none'})")
        return float(values[node.id])
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        left = _eval(node.left, values)
        right = _eval(node.right, values)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalcError(f"exponent {right} is too large (max {MAX_EXPONENT})")
        return _BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARYOPS:
        return _UNARYOPS[type(node.op)](_eval(node.operand, values))
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCS:
            raise CalcError(f"only {', '.join(_FUNCS)} may be called")
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        args = [_eval(a, values) for a in node.args]
        name = node.func.id
        if name == "abs" and len(args) != 1:
            raise CalcError("abs takes one argument")
        if name == "round":
            if len(args) not in (1, 2):
                raise CalcError("round takes one or two arguments")
            if len(args) == 2:
                if not args[1].is_integer():
                    raise CalcError("round's second argument must be a whole number")
                return float(round(args[0], int(args[1])))
            return float(round(args[0]))
        if name in ("min", "max") and len(args) < 2:
            raise CalcError(f"{name} needs at least two arguments")
        return _FUNCS[name](*args)
    raise CalcError(f"{type(node).__name__} is not allowed")


def evaluate(expression: str, values: dict[str, float]) -> float:
    """Evaluate `expression` with `values`; raises CalcError on anything not allowed."""
    if not isinstance(expression, str) or not expression.strip():
        raise CalcError("expression must be a non-empty string")
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise CalcError(f"expression is longer than {MAX_EXPRESSION_CHARS} characters")
    if not isinstance(values, dict):
        raise CalcError("values must be an object mapping names to numbers")
    for name, v in values.items():
        if not isinstance(name, str) or not name.isidentifier() or "__" in name:
            raise CalcError(f"invalid name {name!r}")
        if not _is_number(v) or not math.isfinite(v):
            raise CalcError(f"value of {name!r} must be a finite number, not {v!r}")
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as e:
        raise CalcError(f"invalid expression: {e.msg}") from e
    try:
        result = _eval(tree, values)
    except ZeroDivisionError as e:
        raise CalcError("division by zero") from e
    except OverflowError as e:
        raise CalcError("result is too large") from e
    if not isinstance(result, float) or not math.isfinite(result):
        raise CalcError("result is not a finite real number")
    return result


def call(expression: str, values: dict[str, float]) -> ToolResult:
    try:
        result = evaluate(expression, values)
    except CalcError as e:
        return ToolResult.fail(f"calculate: {e}")
    sid = f"calc:{next(_ids)}"
    return ToolResult(
        ok=True,
        data=[{"source_id": sid, "expression": expression, "values": dict(values),
               "result": result}],
        sources=[Source(source_id=sid, kind="calc")],
    )
