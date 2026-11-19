"""One ingest command (NFR-11). [track-c]

Usage: uv run python -m src.ingest.run_all [--all] [--from STEP]
Runs, in order and idempotently: db setup (schema + read-only role), XBRL facts, coverage
report, 10-K download, section parsing, chunking, Qdrant indexing. Pilot companies by
default; --all for all 50. Prints a summary and exits non-zero if a step failed.
Coverage gaps are reported but are not a failure. --from resumes at a named step.
"""

import argparse
import importlib
import sys
import time
import traceback

# (name, module, function, takes all_companies). Steps are imported lazily, so that e.g.
# fastembed is only loaded when the indexing step runs.
STEPS = [
    ("db", "src.db", "setup", False),
    ("xbrl", "src.ingest.download_xbrl", "main", True),
    ("coverage", "src.ingest.coverage", "main", True),
    ("filings", "src.ingest.download_filings", "main", True),
    ("sections", "src.ingest.parse_sections", "main", False),
    ("chunks", "src.ingest.chunker", "main", False),
    ("index", "src.ingest.index_qdrant", "main", False),
]
STEP_NAMES = [s[0] for s in STEPS]


def _resolve(module: str, func: str):
    return getattr(importlib.import_module(module), func)


def main(all_companies: bool = False, start: str = STEP_NAMES[0]) -> int:
    scope = "all 50 companies" if all_companies else "pilot companies"
    todo = STEPS[STEP_NAMES.index(start):]
    results: list[tuple[str, str, float]] = []
    failed = None
    for i, (name, module, func, takes_all) in enumerate(todo, 1):
        print(f"\n=== [{i}/{len(todo)}] {name} ({module}.{func}, {scope}) ===", flush=True)
        t0 = time.perf_counter()
        try:
            fn = _resolve(module, func)
            rc = fn(all_companies) if takes_all else fn()
        except Exception:
            traceback.print_exc()
            results.append((name, "FAILED", time.perf_counter() - t0))
            failed = name
            break
        # coverage.main returns 1 when there are gaps: report them, but keep going.
        status = "ok (gaps reported)" if name == "coverage" and rc else "ok"
        results.append((name, status, time.perf_counter() - t0))

    print("\n=== summary ===")
    for name, status, dt in results:
        print(f"{name:10} {status:20} {dt:8.1f}s")
    for name in STEP_NAMES[STEP_NAMES.index(start) + len(results):]:
        print(f"{name:10} {'not run':20}")
    if failed:
        print(f"\nstep '{failed}' failed; fix it and resume with: "
              f"uv run python -m src.ingest.run_all{' --all' if all_companies else ''} "
              f"--from {failed}", file=sys.stderr)
        return 1
    print(f"\ndone: {len(results)} step(s), {sum(r[2] for r in results):.1f}s total")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="all 50 companies, not just the pilot")
    ap.add_argument("--from", dest="start", choices=STEP_NAMES, default=STEP_NAMES[0],
                    help="resume at this step (skips the earlier ones)")
    args = ap.parse_args()
    sys.exit(main(args.all, args.start))
