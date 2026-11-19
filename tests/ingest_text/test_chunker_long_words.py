"""Regression: a single whitespace-free "word" larger than the budget must not hang
split_text (Phase 2 code review: infinite loop with unbounded memory growth)."""

import pytest

from src.ingest.chunk_schema import count_tokens
from src.ingest.chunker import _hard_split, split_table, split_text


def test_long_underscore_signature_line_does_not_hang():
    paras = ["Intro sentence here. " * 5, "Signature: " + "_" * 450]
    pieces = split_text(paras, 430, 300, 72)
    assert pieces and all(count_tokens(p) <= 430 for p in pieces)
    assert sum(p.count("_") for p in pieces) >= 450   # nothing dropped (overlap may repeat)


@pytest.mark.parametrize("word", ["_" * 1000, "." * 900, "https://example.com/" + "a" * 3000])
def test_hard_split_respects_limit_and_preserves_text(word):
    parts = _hard_split(word, 100)
    assert "".join(parts) == word
    assert all(count_tokens(p) <= 100 for p in parts)


def test_split_text_many_long_words_terminates_within_budget():
    paras = [" ".join(["-" * 600] * 5), "A normal closing sentence."]
    pieces = split_text(paras, 480, 300, 72)
    assert all(count_tokens(p) <= 480 for p in pieces)
    assert pieces[-1].endswith("A normal closing sentence.")


def test_split_table_with_huge_unbroken_cell():
    table = "| a | b |\n| --- | --- |\n| " + "x" * 3000 + " | 1 |"
    pieces = split_table(table, 200)
    assert pieces and all(count_tokens(p) <= 200 for p in pieces)
