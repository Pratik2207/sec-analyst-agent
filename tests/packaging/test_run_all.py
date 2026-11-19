"""run_all with every step stubbed: order, --all, --from, first failure stops (NFR-11)."""

import subprocess
import sys
from pathlib import Path

import pytest

from src.ingest import run_all

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def calls(monkeypatch):
    log: list[tuple[str, tuple]] = []
    behaviour: dict = {}

    def resolve(module, func):
        name = next(s[0] for s in run_all.STEPS if s[1] == module)

        def step(*args):
            log.append((name, args))
            b = behaviour.get(name)
            if isinstance(b, Exception):
                raise b
            return b
        return step

    monkeypatch.setattr(run_all, "_resolve", resolve)
    return log, behaviour


def test_steps_are_the_existing_entry_points():
    assert [(m, f) for _, m, f, _ in run_all.STEPS] == [
        ("src.db", "setup"),
        ("src.ingest.download_xbrl", "main"),
        ("src.ingest.coverage", "main"),
        ("src.ingest.download_filings", "main"),
        ("src.ingest.parse_sections", "main"),
        ("src.ingest.chunker", "main"),
        ("src.ingest.index_qdrant", "main"),
    ]


def test_runs_every_step_in_order_pilot(calls, capsys):
    log, _ = calls
    assert run_all.main() == 0
    assert [n for n, _ in log] == run_all.STEP_NAMES
    assert dict(log) == {"db": (), "xbrl": (False,), "coverage": (False,),
                         "filings": (False,), "sections": (), "chunks": (), "index": ()}
    out = capsys.readouterr().out
    assert "=== summary ===" in out and "[7/7] index" in out


def test_all_is_passed_through(calls):
    log, _ = calls
    assert run_all.main(all_companies=True) == 0
    assert [args for n, args in log if n in ("xbrl", "coverage", "filings")] == [(True,)] * 3


def test_from_resumes_at_step(calls, capsys):
    log, _ = calls
    assert run_all.main(start="sections") == 0
    assert [n for n, _ in log] == ["sections", "chunks", "index"]
    assert "[1/3] sections" in capsys.readouterr().out


def test_first_failure_stops_with_exit_1(calls, capsys):
    log, behaviour = calls
    behaviour["filings"] = RuntimeError("EDGAR down")
    assert run_all.main() == 1
    assert [n for n, _ in log] == ["db", "xbrl", "coverage", "filings"]
    captured = capsys.readouterr()
    assert "EDGAR down" in captured.err
    assert "--from filings" in captured.err
    assert "FAILED" in captured.out and "not run" in captured.out


def test_coverage_gaps_are_not_a_failure(calls, capsys):
    log, behaviour = calls
    behaviour["coverage"] = 1   # coverage.main returns 1 when there are gaps
    assert run_all.main() == 0
    assert [n for n, _ in log] == run_all.STEP_NAMES
    assert "gaps reported" in capsys.readouterr().out


def test_cli_rejects_unknown_step():
    p = subprocess.run([sys.executable, "-m", "src.ingest.run_all", "--from", "nope"],
                       cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 2 and "invalid choice" in p.stderr
