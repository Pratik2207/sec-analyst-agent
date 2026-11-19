"""Number correctness (PRD 10: exact match within +-1%).

An answer is correct when ANY number it states matches gold_value within 1% relative.
Numbers are read with src.agent.evidence.numbers_in, so "$16.55 billion" is 16.55e9 and
"75.0%" is 75.0. Magnitudes are compared, so a change stated in words ("decreased by
4.34 pp") matches a signed gold (-4.34). For USD/count values the answer may also state the
number in thousands/millions/billions with the unit dropped (tables "in millions").
"""

import re

from src.agent.evidence import numbers_in, strip_computed

REL_TOL = 0.01
_SCALES = (1.0, 1e3, 1e6, 1e9)


def _close(a: float, b: float) -> bool:
    if b == 0:
        return abs(a) < 1e-9
    return abs(a - b) <= abs(b) * REL_TOL


# "%" is followed by punctuation, so the word boundary applies only to the word units
_PERCENT = re.compile(r"[-−]?\$?\d[\d,]*(?:\.\d+)?\s*(?:%|(?:percent(?:age points?)?|pp|bps)\b)",
                      re.I)
_NEGATIVE_WORDS = re.compile(r"\b(loss|losses|negative|deficit|declin\w*|decreas\w*|fell|"
                             r"drop\w*|down|lower|shr[ai]nk\w*|minus)\b|[-−]\$?\d|\(\$?\d", re.I)


def value_matches(n: float, gold: float, unit: str | None) -> bool:
    n, gold = abs(n), abs(gold)
    if unit in ("%", "pp"):
        return _close(n, gold)
    return any(_close(n, gold / s) for s in _SCALES)


_SCALE_WORD = re.compile(r"\b(trillion|billion|million|thousand|bn|mn)\b|\d\s*[kmb]\b", re.I)


def _explicit_scale(token: str) -> bool:
    return bool(_SCALE_WORD.search(token))


def number_correct(answer: str, gold: float, unit: str | None) -> bool:
    text = strip_computed(answer)
    # Phase 5 review: magnitudes are compared, so a negative gold (a net loss, a decline)
    # stated with no loss/decline wording or minus sign is wrong
    if gold < 0 and not _NEGATIVE_WORDS.search(text):
        return False
    if unit in ("%", "pp"):
        return any(value_matches(n, gold, unit) for n in numbers_in(text))
    # a USD/count gold must not be matched by a percentage in the answer
    text = _PERCENT.sub(" ", text)
    for m in _TOKEN.finditer(text):
        vals = numbers_in(m.group(0))
        if not vals:
            continue
        if _explicit_scale(m.group(0)):
            # "$3.9 million" states its own scale: compare as stated, never re-scaled
            if _close(abs(vals[0]), abs(gold)):
                return True
        elif value_matches(vals[0], gold, unit):   # unit dropped: try the table scales
            return True
    return False


_TOKEN = re.compile(r"[-−(]?\$?\d[\d,]*(?:\.\d+)?\)?(?:\s*(?:trillion|billion|million|"
                    r"thousand|bn|mn|[kmb]\b))?", re.I)
