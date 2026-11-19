"""Phase 2 interface contract for retrieval. Owned by the main session.

Search entry point (implemented by track-b in src/retrieval/hybrid_search.py):

    hybrid_search(query: str, filters: SearchFilters | None = None, k: int = 8,
                  use_reranker: bool = True, use_sparse: bool = True,
                  collection: str | None = None) -> list[SearchHit]

Dense + sparse (BM25) candidates are fused with RRF, the top RERANK_POOL are reranked
by the cross-encoder, and the best k are returned. use_reranker/use_sparse exist for
the Phase 5 ablations. collection defaults to settings.qdrant_collection.
"""

from dataclasses import dataclass

RERANK_POOL = 30
DEFAULT_K = 8


@dataclass(frozen=True)
class SearchFilters:
    """Payload filters; a list means "any of". None means no filter."""
    ticker: str | list[str] | None = None
    sector: str | list[str] | None = None
    fiscal_year: int | list[int] | None = None
    item: str | list[str] | None = None


@dataclass(frozen=True)
class SearchHit:
    id: str          # Qdrant point id (chunk_schema.point_id)
    score: float     # reranker score when reranked, else fused RRF score
    payload: dict    # the full Chunk record
