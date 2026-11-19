"""Number correctness (PRD 10: exact match within +-1%).

An answer is correct when ANY number it states matches gold_value within 1% relative.
Numbers are read with src.agent.evidence.numbers_in, so "$16.55 billion" is 16.55e9 and
"75.0%" is 75.0. Magnitudes are compared, so a change stated in words ("decreased by
4.34 pp") matches a signed gold (-4.34). For USD/count values the answer may also state the
number in thousands/millions/billions with the unit dropped (tables "in millions").
"""

from src.agent.evidence import numbers_in, strip_computed

REL_TOL = 0.01
_SCALES = (1.0, 1e3, 1e6, 1e9)


def _close(a: float, b: float) -> bool:
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) <= abs(b) * REL_TOL


def value_matches(n: float, gold: float, unit: str | None) -> bool:
    n, gold = abs(n), abs(gold)
    if unit in ("%", "pp"):
        return _close(n, gold)
    return any(_close(n, gold / s) for s in _SCALES)


def number_correct(answer: str, gold: float, unit: str | None) -> bool:
    return any(value_matches(n, gold, unit) for n in numbers_in(strip_computed(answer)))
