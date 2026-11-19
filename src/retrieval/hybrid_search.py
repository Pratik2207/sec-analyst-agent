"""Hybrid search: dense + BM25 with RRF fusion, payload filters, reranking (FR-6). [track-b]"""

from dataclasses import fields

from qdrant_client import models

from config.settings import get_settings
from src.retrieval.models import BGE_QUERY_INSTRUCTION, dense_model, qdrant, sparse_model
from src.retrieval.reranker import rerank
from src.retrieval.types import DEFAULT_K, RERANK_POOL, SearchFilters, SearchHit


def build_filter(filters: SearchFilters | None) -> models.Filter | None:
    """Scalar -> MatchValue, list -> MatchAny; all conditions combined in `must`."""
    if filters is None:
        return None
    must = []
    for f in fields(filters):
        value = getattr(filters, f.name)
        if value is None:
            continue
        match = (models.MatchAny(any=list(value)) if isinstance(value, list)
                 else models.MatchValue(value=value))
        must.append(models.FieldCondition(key=f.name, match=match))
    return models.Filter(must=must) if must else None


def hybrid_search(query: str, filters: SearchFilters | None = None, k: int = DEFAULT_K,
                  use_reranker: bool = True, use_sparse: bool = True,
                  collection: str | None = None) -> list[SearchHit]:
    collection = collection or get_settings().qdrant_collection
    qfilter = build_filter(filters)
    dense = next(iter(dense_model().query_embed(BGE_QUERY_INSTRUCTION + query))).tolist()

    if use_sparse:
        sp = next(iter(sparse_model().query_embed(query)))
        sparse = models.SparseVector(indices=sp.indices.tolist(), values=sp.values.tolist())
        result = qdrant().query_points(
            collection,
            prefetch=[
                models.Prefetch(query=dense, using="dense", filter=qfilter, limit=RERANK_POOL),
                models.Prefetch(query=sparse, using="sparse", filter=qfilter, limit=RERANK_POOL),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=RERANK_POOL,
            with_payload=True,
        )
    else:  # dense-only ablation; score is the cosine similarity
        result = qdrant().query_points(
            collection, query=dense, using="dense", query_filter=qfilter,
            limit=RERANK_POOL, with_payload=True,
        )

    hits = [SearchHit(id=str(p.id), score=p.score, payload=p.payload) for p in result.points]
    if use_reranker:
        return rerank(query, hits, k)
    return hits[:k]
