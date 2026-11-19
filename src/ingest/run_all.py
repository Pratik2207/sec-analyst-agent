"""One ingest command (NFR-11). [track-c]

Usage: uv run python -m src.ingest.run_all [--all]
Runs, in order and idempotently: db setup (schema + read-only role), XBRL facts, coverage
report, 10-K download, section parsing, chunking, Qdrant indexing. Pilot companies by
default; --all for all 50. Prints a summary and exits non-zero if a step failed.
"""


def main(all_companies: bool = False) -> int:
    raise NotImplementedError("track-c")
