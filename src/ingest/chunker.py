"""Build chunks with context headers and metadata (FR-5, PRD 7.1). [track-a]

Reads data/processed/sections/*.json, writes chunk_schema.CHUNKS_DIR/<accession_no>.jsonl
(records exactly matching chunk_schema.Chunk).

Usage: uv run python -m src.ingest.chunker
"""


def main() -> None:
    raise NotImplementedError("track-a")
