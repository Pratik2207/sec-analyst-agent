"""Hybrid search: dense + BM25 with RRF fusion, payload filters, reranking (FR-6). [track-b]"""

from src.retrieval.types import DEFAULT_K, SearchFilters, SearchHit


def hybrid_search(query: str, filters: SearchFilters | None = None, k: int = DEFAULT_K,
                  use_reranker: bool = True, use_sparse: bool = True,
                  collection: str | None = None) -> list[SearchHit]:
    raise NotImplementedError("track-b")
