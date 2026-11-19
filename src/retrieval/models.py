"""Shared, lazily loaded models and Qdrant client (one instance per process)."""

from functools import lru_cache

from config.settings import get_settings

# fastembed 0.9's TextEmbedding.query_embed is plain embed() for bge-small-en-v1.5 (verified:
# identical vectors), so the bge v1.5 retrieval instruction is added here, for queries only.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


@lru_cache
def dense_model():
    from fastembed import TextEmbedding

    s = get_settings()
    return TextEmbedding(s.embed_model, cache_dir=str(s.model_cache_dir))


@lru_cache
def sparse_model():
    from fastembed import SparseTextEmbedding

    s = get_settings()
    return SparseTextEmbedding(s.sparse_model, cache_dir=str(s.model_cache_dir))


@lru_cache
def rerank_model():
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    s = get_settings()
    return TextCrossEncoder(s.rerank_model, cache_dir=str(s.model_cache_dir))


@lru_cache
def qdrant():
    from qdrant_client import QdrantClient

    return QdrantClient(url=get_settings().qdrant_url)
