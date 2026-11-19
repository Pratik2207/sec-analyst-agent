"""Refusal detection: the exact NOT_FOUND string, or a clear "not found / no information /
does not provide" answer. Only the first sentence is checked, so an answer that gives a
value and then notes a missing detail is not a refusal."""

import re

from src.agent.evidence import numbers_in
from src.agent.fast_path import NOT_FOUND

_REFUSAL = re.compile(
    r"\bnot (?:be )?(?:found|available|disclosed|reported|provided|mentioned|included|stated)\b"
    r"|\bno (?:information|data|mention|record|figures?|details?)\b"
    r"|\b(?:does|do|did) not (?:provide|contain|include|disclose|mention|report|specify|"
    r"state|have|cover)\b"
    r"|\b(?:cannot|can't|can not|unable to) (?:be )?(?:find|found|determine|answer|provide|"
    r"locate|identify)\b"
    r"|\binsufficient (?:information|evidence|data)\b"
    # Phase 5 review: common paraphrases the baseline uses
    r"|\b(?:could not|couldn't|was unable to|were unable to) (?:find|locate|identify)\b"
    r"|\b(?:doesn't|don't|didn't|isn't|aren't|wasn't) (?:mention|contain|include|provide|"
    r"disclose|report|state|specify|cover|available|listed|given)\b"
    r"|\bnot (?:yet |currently )?available\b"
    r"|\bno \w+ (?:data|information|figures?) (?:is |are )?(?:available|provided|given)\b"
    r"|\bnot (?:in|part of) the (?:provided |given )?(?:context|filings?|documents?|evidence)\b",
    re.I)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def is_refusal(answer: str) -> bool:
    text = (answer or "").strip()
    if not text or text.lower() == NOT_FOUND.lower():
        return True
    first = _SENTENCE_END.split(text, maxsplit=1)[0]
    # "Intel did not report a gross profit line; its gross margin was 32.7%" answers with a
    # number: not a refusal
    if numbers_in(first):
        return False
    return bool(_REFUSAL.search(first))
