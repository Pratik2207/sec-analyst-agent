"""Cross-encoder reranker (settings.rerank_model via fastembed). [track-b]"""

from src.retrieval.types import SearchHit


def rerank(query: str, hits: list[SearchHit], top_k: int) -> list[SearchHit]:
    """Return the top_k hits by cross-encoder score (SearchHit.score = reranker score)."""
    raise NotImplementedError("track-b")
