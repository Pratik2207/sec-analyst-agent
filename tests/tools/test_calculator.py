"""calculate tool (FR-9): restricted AST evaluator."""

import pytest

from src.tools import calculator

REJECTED = [
    ("__import__('os')", {}),
    ("().__class__", {}),
    ("x.real", {"x": 1}),
    ("[1][0]", {}),
    ("lambda: 1", {}),
    ("open('f')", {}),
    ("2**10**10", {}),
    ("y + 1", {"x": 1}),            # unknown name
    ("'abc'", {}),                  # string
    ("True", {}),                   # bool constant
    ("x and 1", {"x": 1}),          # boolean op
    ("x > 1", {"x": 1}),            # comparison
    ("[i for i in (1, 2)]", {}),    # comprehension
    ("sum((1, 2))", {}),            # call outside the allow-list
    ("__builtins__", {}),           # dunder name
    ("x.__class__", {"x": 1}),
    ("abs(x=1)", {}),               # keyword argument
    ("(1, 2)", {}),                 # tuple
    ("1 if x else 2", {"x": 1}),    # conditional
    ("x / 0", {"x": 1}),            # division by zero
    ("x % 0", {"x": 1}),
    ("1 +", {}),                    # syntax error
    ("", {}),
    ("1" + "+1" * 300, {}),         # too long
    ("x + 1", {"x": True}),         # bool value
    ("x + 1", {"x": "5"}),          # string value
    ("__x + 1", {"__x": 1}),        # dunder value name
    ("(-8) ** 0.5", {}),            # complex result
    ("1e300 * 1e300", {}),          # overflow to inf
    ("1j", {}),                     # complex constant
    ("max(1)", {}),
    ("round(x, 1.5)", {"x": 1.234}),
]


@pytest.mark.parametrize("expression,values", REJECTED)
def test_rejected(expression, values):
    res = calculator.call(expression, values)
    assert res.ok is False
    assert res.error and res.data == [] and res.sources == []


def test_values_must_be_a_dict():
    assert not calculator.call("1 + 1", [1, 2]).ok


def test_acceptance_ratio():
    res = calculator.call("(rd / revenue) * 100", {"rd": 1, "revenue": 4})
    assert res.ok
    item = res.data[0]
    assert item["result"] == 25.0
    assert item["expression"] == "(rd / revenue) * 100"
    assert item["values"] == {"rd": 1, "revenue": 4}


@pytest.mark.parametrize("expression,values,expected", [
    ("a + b - c", {"a": 1, "b": 2, "c": 0.5}, 2.5),
    ("(new - old) / old * 100", {"new": 130497, "old": 60922}, (130497 - 60922) / 60922 * 100),
    ("-x", {"x": 3}, -3.0),
    ("+x", {"x": 3}, 3.0),
    ("7 // 2", {}, 3.0),
    ("7 % 4", {}, 3.0),
    ("2 ** 10", {}, 1024.0),
    ("2 ** -2", {}, 0.25),
    ("abs(x)", {"x": -2.5}, 2.5),
    ("round(x, 2)", {"x": 3.14159}, 3.14),
    ("round(x)", {"x": 2.6}, 3.0),
    ("min(a, b, 1)", {"a": 5, "b": 2}, 1.0),
    ("max(a, b)", {"a": 5, "b": 2}, 5.0),
    ("1 / 3", {}, 1 / 3),
    ("1e3 * x", {"x": 2}, 2000.0),
])
def test_allowed(expression, values, expected):
    res = calculator.call(expression, values)
    assert res.ok, res.error
    assert isinstance(res.data[0]["result"], float)
    assert res.data[0]["result"] == pytest.approx(expected)


def test_source_ids_unique_and_resolve():
    a = calculator.call("1 + 1", {})
    b = calculator.call("2 + 2", {})
    for res in (a, b):
        sid = res.data[0]["source_id"]
        assert sid.startswith("calc:")
        assert res.source(sid).kind == "calc"
        assert res.source(sid).citation() is None
    assert a.data[0]["source_id"] != b.data[0]["source_id"]


def test_spec_shape():
    fn = calculator.SPEC["function"]
    assert fn["name"] == "calculate"
    assert fn["parameters"]["required"] == ["expression", "values"]
