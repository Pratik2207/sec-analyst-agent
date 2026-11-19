"""Extra Phase 2 unit tests for indexing and hybrid search (stubbed models/Qdrant)."""

from src.ingest import index_qdrant
from src.ingest.chunk_schema import read_chunks, write_chunks
from src.retrieval import hybrid_search as hs
from src.retrieval.types import DEFAULT_K, RERANK_POOL, SearchFilters
from tests.retrieval.test_unit import FIXTURE, FakeQdrant, _patch_models, _points


def test_reindex_with_empty_chunk_file_removes_filing(monkeypatch, tmp_path):
    """A filing that re-chunks to 0 chunks (file `<accession_no>.jsonl` is empty) must not
    leave its old points behind (NFR-8: re-runnable, no stale data)."""
    client = FakeQdrant()
    _patch_models(monkeypatch, client, index_qdrant)
    chunks = list(read_chunks(FIXTURE))
    nvda_acc = next(c["accession_no"] for c in chunks if c["ticker"] == "NVDA")
    full = tmp_path / "all.jsonl"
    write_chunks(full, chunks)
    index_qdrant.index_chunks([full], collection="c")
    empty = tmp_path / f"{nvda_acc}.jsonl"
    write_chunks(empty, [])
    index_qdrant.index_chunks([empty], collection="c")
    assert not [p for p in client.upserted.values() if p.payload["accession_no"] == nvda_acc]


def test_default_k_is_8_and_pool_is_30(monkeypatch):
    client = FakeQdrant(_points(RERANK_POOL))
    _patch_models(monkeypatch, client, hs)
    seen = {}

    def fake_rerank(query, hits, top_k):
        seen.update(n=len(hits), k=top_k)
        return hits[:top_k]

    monkeypatch.setattr(hs, "rerank", fake_rerank)
    hits = hs.hybrid_search("q", collection="c")
    assert DEFAULT_K == 8 and RERANK_POOL == 30
    assert seen == {"n": 30, "k": 8} and len(hits) == 8


def test_default_collection_from_settings(monkeypatch):
    client = FakeQdrant(_points(3))
    _patch_models(monkeypatch, client, hs)
    hs.hybrid_search("q", SearchFilters(), use_reranker=False)
    assert client.calls[0][0] == "filings"
    assert client.calls[0][1]["prefetch"][0].filter is None   # empty filters -> no filter


def test_fewer_hits_than_k(monkeypatch):
    client = FakeQdrant(_points(3))
    _patch_models(monkeypatch, client, hs)
    assert len(hs.hybrid_search("q", k=8, use_reranker=False, collection="c")) == 3
