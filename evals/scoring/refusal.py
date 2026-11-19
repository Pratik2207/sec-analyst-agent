"""Refusal detection: the exact NOT_FOUND string, or a clear "not found / no information /
does not provide" answer. Only the first sentence is checked, so an answer that gives a
value and then notes a missing detail is not a refusal."""

import re

from src.agent.fast_path import NOT_FOUND

_REFUSAL = re.compile(
    r"\bnot (?:be )?(?:found|available|disclosed|reported|provided|mentioned|included|stated)\b"
    r"|\bno (?:information|data|mention|record|figures?|details?)\b"
    r"|\b(?:does|do|did) not (?:provide|contain|include|disclose|mention|report|specify|"
    r"state|have|cover)\b"
    r"|\b(?:cannot|can't|can not|unable to) (?:be )?(?:find|found|determine|answer|provide|"
    r"locate|identify)\b"
    r"|\binsufficient (?:information|evidence|data)\b",
    re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def is_refusal(answer: str) -> bool:
    text = (answer or "").strip()
    if not text or text.lower() == NOT_FOUND.lower():
        return True
    return bool(_REFUSAL.search(_SENTENCE_END.split(text, maxsplit=1)[0]))
