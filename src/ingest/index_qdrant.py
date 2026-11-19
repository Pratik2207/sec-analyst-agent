"""Embed chunks (dense + BM25 sparse) and upsert them into Qdrant (FR-5, NFR-8). [track-b]

Reads chunk_schema.CHUNKS_DIR/*.jsonl. Collection: named vectors "dense" (cosine,
settings.embed_dim) and sparse "sparse" (BM25, IDF modifier); payload indexes on
ticker, sector, fiscal_year, item. Point IDs: chunk_schema.point_id(...).

Usage: uv run python -m src.ingest.index_qdrant
"""

from pathlib import Path


def index_chunks(paths: list[Path], collection: str | None = None) -> int:
    """Upsert every chunk in `paths`; returns the number of points written."""
    raise NotImplementedError("track-b")


def main() -> None:
    raise NotImplementedError("track-b")
