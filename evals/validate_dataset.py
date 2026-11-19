"""Validate evals/dataset.jsonl (Phase 5 AC1). [track-a]

Usage: uv run python -m evals.validate_dataset [path] [--facts FILE] [--chunks DIR]
Checks: schema (evals.schema.DatasetItem), EXPECTED_COUNTS per type, unique ids, number
questions have gold_value + gold_sources and the value matches evals/data/facts_pilot.json,
text questions have gold_sources + gold_contains, unanswerable have no gold_value.
Exit code 1 with a list of problems.

The facts check is skipped (with a warning) when the facts file is missing, and the
gold_contains check is skipped when the chunks dir is missing.
"""

import argparse
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

from pydantic import ValidationError

from evals.schema import DATASET, EXPECTED_COUNTS, DatasetItem

ROOT = Path(__file__).resolve().parent.parent
FACTS = ROOT / "evals" / "data" / "facts_pilot.json"
CHUNKS = ROOT / "data" / "processed" / "chunks"

ID_PREFIX = {"number": "num", "text": "txt", "multihop": "mh", "unanswerable": "na"}
# used only when notes has no "metric=..."; first match wins, so specific phrases come first
METRIC_WORDS = [
    ("gross_profit", ("gross profit",)),
    ("operating_income", ("operating income",)),
    ("net_income", ("net income", "net loss")),
    ("rd_expense", ("r&d", "research and development")),
    ("total_assets", ("total assets",)),
    ("revenue", ("revenue", "sales")),
]


def infer_metric(item: DatasetItem) -> str | None:
    m = re.search(r"metric=(\w+)", item.notes)
    if m:
        return m.group(1)
    q = item.question.lower()
    for metric, words in METRIC_WORDS:
        if any(w in q for w in words):
            return metric
    return None


def load_facts(path: Path) -> dict[tuple[str, int, str], dict]:
    with open(path, encoding="utf-8") as f:
        return {(r["ticker"], r["fiscal_year"], r["metric"]): r for r in json.load(f)}


def load_chunks(chunks_dir: Path) -> dict[tuple[str, int, str], list[str]]:
    """(ticker, fiscal_year, item) -> lowercased chunk texts."""
    out: dict[tuple[str, int, str], list[str]] = {}
    for p in sorted(chunks_dir.glob("*.jsonl")):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    key = (r["ticker"], r["fiscal_year"], r["item"])
                    out.setdefault(key, []).append(r["text"].lower())
    return out


def validate(
    path: Path = DATASET,
    facts_path: Path | None = FACTS,
    chunks_dir: Path | None = CHUNKS,
    expected_counts: dict[str, int] | None = EXPECTED_COUNTS,
) -> tuple[list[str], list[str]]:
    """Return (problems, warnings)."""
    problems: list[str] = []
    warnings: list[str] = []
    items: list[DatasetItem] = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                items.append(DatasetItem.model_validate(json.loads(line)))
            except (json.JSONDecodeError, ValidationError) as e:
                problems.append(f"line {n}: invalid item: {e}".splitlines()[0])

    facts = None
    if facts_path and Path(facts_path).exists():
        facts = load_facts(Path(facts_path))
    else:
        warnings.append(f"facts file not found ({facts_path}); number values not checked")
    chunks = None
    if chunks_dir and Path(chunks_dir).is_dir():
        chunks = load_chunks(Path(chunks_dir))
    else:
        warnings.append(f"chunks dir not found ({chunks_dir}); gold_contains not checked")

    if expected_counts is not None:
        counts = Counter(it.type for it in items)
        for t, want in expected_counts.items():
            if counts.get(t, 0) != want:
                problems.append(f"count: {t} has {counts.get(t, 0)}, expected {want}")

    for i, c in Counter(it.id for it in items).items():
        if c > 1:
            problems.append(f"{i}: duplicate id ({c} times)")
    seen_q: dict[str, str] = {}
    for it in items:
        q = " ".join(it.question.lower().split())
        if not q:
            problems.append(f"{it.id}: empty question")
        elif q in seen_q:
            problems.append(f"{it.id}: duplicate question (same as {seen_q[q]})")
        else:
            seen_q[q] = it.id
        if not re.fullmatch(rf"{ID_PREFIX[it.type]}-\d{{3}}", it.id):
            problems.append(f"{it.id}: id does not match type {it.type} "
                            f"(expected {ID_PREFIX[it.type]}-NNN)")
        if not it.gold_answer.strip():
            problems.append(f"{it.id}: empty gold_answer")
        problems += [f"{it.id}: {p}" for p in check_item(it, facts, chunks)]
    return problems, warnings


def check_item(it: DatasetItem, facts, chunks) -> list[str]:
    p: list[str] = []
    if it.type == "number":
        if it.gold_value is None:
            p.append("number item has no gold_value")
        if not it.gold_sources:
            p.append("number item has no gold_sources")
        if it.gold_value is None or not it.gold_sources or facts is None:
            return p
        metric = infer_metric(it)
        if metric is None:
            return p + ["cannot infer metric (add notes 'metric=...')"]
        s = it.gold_sources[0]
        fact = facts.get((s.ticker, s.fiscal_year, metric))
        if fact is None:
            return p + [f"no fact for {s.ticker} FY{s.fiscal_year} {metric}"]
        if not math.isclose(it.gold_value, fact["value"], rel_tol=1e-9, abs_tol=0.5):
            p.append(f"gold_value {it.gold_value} != fact {fact['value']} "
                     f"({s.ticker} FY{s.fiscal_year} {metric})")
        if s.accession_no and s.accession_no != fact["accession_no"]:
            p.append(f"accession_no {s.accession_no} != fact {fact['accession_no']}")
    elif it.type == "text":
        if not it.gold_sources:
            p.append("text item has no gold_sources")
        if not it.gold_contains:
            p.append("text item has no gold_contains")
        if not it.gold_sources or not it.gold_contains or chunks is None:
            return p
        phrases = [c.lower() for c in it.gold_contains]
        found = any(
            all(ph in text for ph in phrases)
            for s in it.gold_sources
            for text in chunks.get((s.ticker, s.fiscal_year, s.item), [])
        )
        if not found:
            p.append(f"no chunk of {[(s.ticker, s.fiscal_year, s.item) for s in it.gold_sources]}"
                     f" contains all of {it.gold_contains}")
    elif it.type == "multihop":
        if not it.gold_sources:
            p.append("multihop item has no gold_sources")
        if it.gold_value is not None and not it.unit:
            p.append("multihop gold_value has no unit")
    elif it.type == "unanswerable":
        if it.gold_value is not None:
            p.append("unanswerable item has a gold_value")
        if it.gold_sources:
            p.append("unanswerable item has gold_sources")
    return p


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", type=Path, default=DATASET)
    ap.add_argument("--facts", type=Path, default=FACTS)
    ap.add_argument("--chunks", type=Path, default=CHUNKS)
    a = ap.parse_args(argv)
    problems, warnings = validate(a.path, a.facts, a.chunks)
    for w in warnings:
        print(f"WARNING: {w}")
    for p in problems:
        print(f"PROBLEM: {p}")
    if problems:
        print(f"{len(problems)} problem(s) in {a.path}")
        return 1
    print(f"OK: {a.path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
