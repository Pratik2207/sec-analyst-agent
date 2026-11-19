"""Phase 5 eval runner (FR-17). [track-b]

Usage: uv run python -m evals.run_eval [--run-id ID] [--dataset PATH] [--systems ...]
       [--limit N] [--types ...] [--skip-judge] [--report-only]
Runs SYSTEMS + END_TO_END_ABLATIONS (evals.systems) on the dataset, caching every RunResult
under evals/results/<run_id>/raw/<system>/<qid>.json (resumable), scores them
(evals/scoring), runs the RETRIEVAL_ABLATIONS recall@10, and writes
evals/results/<run_id>/report.md (+ scores.json).
"""


def main() -> int:
    raise NotImplementedError("track-b")
