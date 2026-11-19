"""Embed chunks (dense + BM25 sparse) and upsert them into Qdrant (FR-5, NFR-8). [track-b]

Reads chunk_schema.CHUNKS_DIR/*.jsonl. Collection: named vectors "dense" (cosine,
settings.embed_dim) and sparse "sparse" (BM25, IDF modifier); payload indexes on
ticker, sector, fiscal_year, item. Point IDs: chunk_schema.point_id(...).

Usage: uv run python -m src.ingest.index_qdrant
"""

import time
from pathlib import Path

from qdrant_client import QdrantClient, models

from config.settings import get_settings
from src.ingest.chunk_schema import CHUNKS_DIR, chunk_body, point_id, read_chunks
from src.retrieval.models import dense_model, qdrant, sparse_model

BATCH = 64
KEYWORD_FIELDS = ("ticker", "sector", "item", "accession_no")
INTEGER_FIELDS = ("fiscal_year",)


def ensure_collection(client: QdrantClient, name: str) -> None:
    """Create the collection and its payload indexes if missing."""
    if client.collection_exists(name):
        return
    client.create_collection(
        name,
        vectors_config={"dense": models.VectorParams(
            size=get_settings().embed_dim, distance=models.Distance.COSINE)},
        sparse_vectors_config={"sparse": models.SparseVectorParams(
            modifier=models.Modifier.IDF)},
    )
    for field in KEYWORD_FIELDS:
        client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
    for field in INTEGER_FIELDS:
        client.create_payload_index(name, field, models.PayloadSchemaType.INTEGER)


def _points(chunks: list[dict]) -> list[models.PointStruct]:
    texts = [c["text"] for c in chunks]
    dense = dense_model().passage_embed(texts, batch_size=BATCH)
    sparse = sparse_model().passage_embed(texts, batch_size=BATCH)
    return [
        models.PointStruct(
            id=point_id(c["accession_no"], c["item"], c["chunk_index"]),
            vector={"dense": d.tolist(),
                    "sparse": models.SparseVector(indices=s.indices.tolist(),
                                                  values=s.values.tolist())},
            payload=c,
        )
        for c, d, s in zip(chunks, dense, sparse, strict=True)
    ]


def _delete_filing(client: QdrantClient, collection: str, accession_no: str) -> None:
    """Drop a filing's existing points, so a re-chunk that yields fewer chunks
    leaves no stale points behind."""
    client.delete(collection, points_selector=models.FilterSelector(filter=models.Filter(
        must=[models.FieldCondition(key="accession_no",
                                    match=models.MatchValue(value=accession_no))])))


def index_chunks(paths: list[Path], collection: str | None = None,
                 use_headers: bool = True) -> int:
    """Replace each file's filing in the collection; returns the number of points written.
    Each chunk file holds one filing (chunk_schema: CHUNKS_DIR/<accession_no>.jsonl).
    use_headers=False indexes the bodies without context headers (Phase 5 ablation; the
    payload text is the body too, so the reranker also sees no header)."""
    collection = collection or get_settings().qdrant_collection
    client = qdrant()
    ensure_collection(client, collection)
    n = 0
    for path in paths:
        chunks = list(read_chunks(path))
        if not use_headers:
            chunks = [{**c, "text": chunk_body(c)} for c in chunks]
        # The file name is the accession number (chunk_schema contract), so an empty file
        # still clears its filing.
        # Embed the whole filing before touching the collection, so an embedding failure
        # (e.g. out of memory) leaves the previously indexed version in place.
        points = [p for i in range(0, len(chunks), BATCH) for p in _points(chunks[i:i + BATCH])]
        for accession_no in {path.stem} | {c["accession_no"] for c in chunks}:
            _delete_filing(client, collection, accession_no)
        for i in range(0, len(points), BATCH):
            client.upsert(collection, points[i:i + BATCH])
        n += len(points)
    return n


def main() -> None:
    s = get_settings()
    paths = sorted(CHUNKS_DIR.glob("*.jsonl"))
    t0 = time.perf_counter()
    n = index_chunks(paths)
    dt = time.perf_counter() - t0
    total = qdrant().count(s.qdrant_collection, exact=True).count
    print(f"indexed {n} chunks from {len(paths)} files in {dt:.1f}s "
          f"({n / dt if dt else 0:.1f} chunks/s); "
          f"collection {s.qdrant_collection!r} has {total} points")


if __name__ == "__main__":
    main()
