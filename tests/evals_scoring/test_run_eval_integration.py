"""The real runner on the 6-question sample (needs Postgres, Qdrant and Ollama)."""

import json
import shutil

import pytest

from evals import run_eval

pytestmark = pytest.mark.integration
SAMPLE = run_eval.RESULTS_DIR.parent / "sample_dataset.jsonl"


def test_run_eval_on_sample_subset():
    run_id = "pytest-sample"
    out = run_eval.RESULTS_DIR / run_id
    shutil.rmtree(out, ignore_errors=True)
    try:
        assert run_eval.main(["--run-id", run_id, "--dataset", str(SAMPLE), "--limit", "2",
                              "--skip-judge", "--skip-noheader"]) == 0
        scores = json.loads((out / "scores.json").read_text(encoding="utf-8"))
        assert {"agent", "baseline", "agent:no_sql"} <= set(scores["summary"])
        assert (out / "report.md").read_text(encoding="utf-8").count("NFR-") >= 5
        rows = scores["rows"]
        assert len(rows) == 6 and not [r for r in rows if r["error"]]
        # the first two sample items are number questions: scored without the judge
        assert scores["summary"]["agent"]["number"]["scored"] == 2
    finally:
        shutil.rmtree(out, ignore_errors=True)
