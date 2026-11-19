"""Cross-encoder reranker (settings.rerank_model via fastembed). [track-b]"""

from dataclasses import replace

from src.retrieval.models import rerank_model
from src.retrieval.types import SearchHit


def rerank(query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    """Return the top_k hits by cross-encoder score (SearchHit.score = reranker score)."""
    if not hits:
        return []
    scores = rerank_model().rerank(query, [h.payload["text"] for h in hits])
    scored = [replace(h, score=float(s)) for h, s in zip(hits, scores, strict=True)]
    return sorted(scored, key=lambda h: h.score, reverse=True)[:top_k]
