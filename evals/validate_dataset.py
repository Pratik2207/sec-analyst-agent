"""Validate evals/dataset.jsonl (Phase 5 AC1). [track-a]

Usage: uv run python -m evals.validate_dataset [path]
Checks: schema (evals.schema.DatasetItem), EXPECTED_COUNTS per type, unique ids, number
questions have gold_value + gold_sources and the value matches evals/data/facts_pilot.json,
text questions have gold_sources + gold_contains, unanswerable have no gold_value.
Exit code 1 with a list of problems.
"""


def main() -> int:
    raise NotImplementedError("track-a")
