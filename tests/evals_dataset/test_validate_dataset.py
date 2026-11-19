"""Unit tests for evals.validate_dataset (Phase 5, track-a)."""

import json

import pytest

from evals import validate_dataset as vd
from evals.schema import DATASET, EXPECTED_COUNTS

ONE_EACH = {"number": 1, "text": 1, "multihop": 1, "unanswerable": 1}

FACTS = [
    {"ticker": "INTC", "fiscal_year": 2024, "metric": "rd_expense", "value": 16546000000.0,
     "accession_no": "0000050863-25-000009"},
    {"ticker": "INTC", "fiscal_year": 2024, "metric": "revenue", "value": 53101000000.0,
     "accession_no": "0000050863-25-000009"},
]
CHUNKS = [
    {"ticker": "NVDA", "fiscal_year": 2025, "item": "7", "text":
     "[NVDA | 10-K]\n\nGross margin increased due to a higher mix of Data Center revenue."},
    {"ticker": "NVDA", "fiscal_year": 2025, "item": "1A", "text": "Export controls on GPUs."},
]


def num(**kw):
    d = {"id": "num-001", "type": "number", "question": "What was Intel's R&D expense in FY2024?",
         "gold_answer": "$16.55 billion.", "gold_value": 16546000000.0, "unit": "USD",
         "gold_sources": [{"ticker": "INTC", "fiscal_year": 2024, "item": "8",
                           "accession_no": "0000050863-25-000009"}],
         "notes": "metric=rd_expense"}
    return d | kw


def txt(**kw):
    d = {"id": "txt-001", "type": "text", "question": "Why did NVIDIA's gross margin change?",
         "gold_answer": "Higher Data Center mix.",
         "gold_sources": [{"ticker": "NVDA", "fiscal_year": 2025, "item": "7"}],
         "gold_contains": ["gross margin", "DATA CENTER"]}
    return d | kw


def mh(**kw):
    d = {"id": "mh-001", "type": "multihop", "question": "Which bank earned the most in FY2025?",
         "gold_answer": "JPM.", "gold_sources": [{"ticker": "JPM", "fiscal_year": 2025}]}
    return d | kw


def na(**kw):
    d = {"id": "na-001", "type": "unanswerable", "question": "What was NVIDIA's revenue in FY2030?",
         "gold_answer": "Not found in the filings."}
    return d | kw


@pytest.fixture
def env(tmp_path):
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(FACTS), encoding="utf-8")
    chunks = tmp_path / "chunks"
    chunks.mkdir()
    (chunks / "a.jsonl").write_text("\n".join(json.dumps(c) for c in CHUNKS), encoding="utf-8")

    def run(items, counts=ONE_EACH, facts_path=facts, chunks_dir=chunks):
        path = tmp_path / "ds.jsonl"
        lines = [i if isinstance(i, str) else json.dumps(i) for i in items]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return vd.validate(path, facts_path, chunks_dir, counts)

    return run


def good():
    return [num(), txt(), mh(), na()]


def test_good_fixture_passes(env):
    problems, warnings = env(good())
    assert problems == [] and warnings == []


def test_counts_checked_against_expected(env):
    problems, _ = env(good(), counts=EXPECTED_COUNTS)
    assert sum(p.startswith("count:") for p in problems) == 4


def test_number_value_mismatch(env):
    problems, _ = env([num(gold_value=16.5e9), txt(), mh(), na()])
    assert any("num-001: gold_value" in p for p in problems)


def test_number_accession_mismatch(env):
    src = {"ticker": "INTC", "fiscal_year": 2024, "item": "8", "accession_no": "x"}
    problems, _ = env([num(gold_sources=[src]), txt(), mh(), na()])
    assert any("accession_no x" in p for p in problems)


def test_number_metric_inferred_from_question(env):
    item = num(notes="", question="What was Intel's revenue in 2024?", gold_value=53101000000.0)
    assert env([item, txt(), mh(), na()])[0] == []
    item = num(notes="", question="What was Intel's revenue in 2024?")  # R&D value
    assert any("gold_value" in p for p in env([item, txt(), mh(), na()])[0])


def test_number_missing_fact_and_missing_value(env):
    problems, _ = env([num(notes="metric=gross_profit"), txt(), mh(), na()])
    assert any("no fact for INTC FY2024 gross_profit" in p for p in problems)
    problems, _ = env([num(gold_value=None), txt(), mh(), na()])
    assert any("no gold_value" in p for p in problems)


def test_text_phrase_must_be_in_a_chunk(env):
    problems, _ = env([num(), txt(gold_contains=["gross margin", "Gaming"]), mh(), na()])
    assert any("txt-001: no chunk" in p for p in problems)


def test_text_phrases_must_share_one_chunk_of_that_item(env):
    # "export controls" is in item 1A, not item 7
    problems, _ = env([num(), txt(gold_contains=["gross margin", "export controls"]), mh(), na()])
    assert any("txt-001: no chunk" in p for p in problems)


def test_text_needs_sources_and_contains(env):
    problems, _ = env([num(), txt(gold_contains=[], gold_sources=[]), mh(), na()])
    assert any("no gold_sources" in p for p in problems)
    assert any("no gold_contains" in p for p in problems)


def test_missing_data_only_warns(env, tmp_path):
    items = [num(gold_value=1.0), txt(gold_contains=["absent phrase"]), mh(), na()]
    problems, warnings = env(items, facts_path=tmp_path / "nope.json",
                             chunks_dir=tmp_path / "nodir")
    assert problems == []
    assert len(warnings) == 2


def test_ids_and_questions(env):
    items = [num(), num(id="num-002"), txt(id="num-003"), mh(id="mh-001"), mh(question=" "),
             na(question="what was nvidia's  revenue in fy2030?", id="na-002"), na()]
    problems, _ = env(items, counts=None)
    assert any("mh-001: duplicate id" in p for p in problems)
    assert any("num-002: duplicate question" in p for p in problems)
    assert any("num-003: id does not match type text" in p for p in problems)
    assert any("empty question" in p for p in problems)
    assert any("na-001: duplicate question" in p for p in problems)


def test_multihop_and_unanswerable_rules(env):
    items = [num(), txt(), mh(gold_sources=[], gold_value=1.0),
             na(gold_value=3.0, gold_sources=[{"ticker": "NVDA", "fiscal_year": 2030}])]
    problems, _ = env(items)
    assert any("multihop item has no gold_sources" in p for p in problems)
    assert any("multihop gold_value has no unit" in p for p in problems)
    assert any("unanswerable item has a gold_value" in p for p in problems)
    assert any("unanswerable item has gold_sources" in p for p in problems)


def test_schema_errors_reported(env):
    problems, _ = env([num(), txt(), mh(), na(), '{"id": "x"}', "not json"], counts=None)
    assert sum("invalid item" in p for p in problems) == 2


def test_main_exit_codes(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(json.dumps(na()) + "\n", encoding="utf-8")
    args = [str(bad), "--facts", str(tmp_path / "x"), "--chunks", str(tmp_path / "none")]
    assert vd.main(args) == 1
    assert "PROBLEM: count:" in capsys.readouterr().out


def test_real_dataset_passes(capsys):
    assert vd.main([str(DATASET)]) == 0, capsys.readouterr().out


def test_real_dataset_matches_builder():
    """dataset.jsonl is exactly what evals.build_dataset produces (needs the facts file)."""
    if not vd.FACTS.exists():
        pytest.skip("evals/data/facts_pilot.json not present")
    from evals import build_dataset

    built = [it.model_dump() for it in build_dataset.build()]
    with open(DATASET, encoding="utf-8") as f:
        on_disk = [vd.DatasetItem.model_validate(json.loads(line)).model_dump()
                   for line in f if line.strip()]
    assert built == on_disk
