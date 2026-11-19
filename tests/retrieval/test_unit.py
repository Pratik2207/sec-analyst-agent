"""Unit tests for indexing, filters, fusion call shape and reranking (no Qdrant, no models)."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
from qdrant_client import models

from src.ingest import index_qdrant
from src.ingest.chunk_schema import point_id, read_chunks, write_chunks
from src.retrieval import hybrid_search as hs
from src.retrieval import reranker
from src.retrieval.models import BGE_QUERY_INSTRUCTION
from src.retrieval.types import RERANK_POOL, SearchFilters, SearchHit

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "chunks_sample.jsonl"


# ---- filters --------------------------------------------------------------------------------

def test_build_filter_none_and_empty():
    assert hs.build_filter(None) is None
    assert hs.build_filter(SearchFilters()) is None


def test_build_filter_scalar_and_list():
    f = hs.build_filter(SearchFilters(ticker="JPM", sector=["banks", "pharma"],
                                      fiscal_year=[2024, 2025], item="1A"))
    by_key = {c.key: c.match for c in f.must}
    assert set(by_key) == {"ticker", "sector", "fiscal_year", "item"}
    assert by_key["ticker"] == models.MatchValue(value="JPM")
    assert by_key["item"] == models.MatchValue(value="1A")
    assert by_key["sector"] == models.MatchAny(any=["banks", "pharma"])
    assert by_key["fiscal_year"] == models.MatchAny(any=[2024, 2025])


def test_build_filter_int_scalar():
    f = hs.build_filter(SearchFilters(fiscal_year=2024))
    assert f.must == [models.FieldCondition(key="fiscal_year",
                                            match=models.MatchValue(value=2024))]


# ---- stubs ----------------------------------------------------------------------------------

class FakeDense:
    def __init__(self):
        self.queries = []

    def query_embed(self, q):
        self.queries.append(q)
        yield np.zeros(4)

    def passage_embed(self, texts, batch_size=64):
        for t in texts:
            yield np.full(4, len(t), dtype=float)


class FakeSparse:
    def __init__(self):
        self.queries = []

    def query_embed(self, q):
        self.queries.append(q)
        yield SimpleNamespace(indices=np.array([1, 2]), values=np.array([1.0, 1.0]))

    def passage_embed(self, texts, batch_size=64):
        for _ in texts:
            yield SimpleNamespace(indices=np.array([3]), values=np.array([0.5]))


class FakeQdrant:
    def __init__(self, points=()):
        self.points = list(points)
        self.calls = []
        self.upserted = {}

    def query_points(self, collection, **kw):
        self.calls.append((collection, kw))
        return SimpleNamespace(points=self.points)

    def collection_exists(self, name):
        return True

    def upsert(self, collection, points):
        for p in points:
            self.upserted[p.id] = p

    def delete(self, collection, points_selector):
        (cond,) = points_selector.filter.must
        acc = cond.match.value
        self.upserted = {k: p for k, p in self.upserted.items()
                         if p.payload["accession_no"] != acc}


def _patch_models(monkeypatch, client, module):
    dense, sparse = FakeDense(), FakeSparse()
    monkeypatch.setattr(module, "dense_model", lambda: dense)
    monkeypatch.setattr(module, "sparse_model", lambda: sparse)
    monkeypatch.setattr(module, "qdrant", lambda: client)
    return dense, sparse


def _points(n):
    return [SimpleNamespace(id=f"id{i}", score=1.0 / (i + 1), payload={"text": f"doc {i}"})
            for i in range(n)]


# ---- hybrid_search --------------------------------------------------------------------------

def test_hybrid_rrf_query_shape_and_no_rerank(monkeypatch):
    client = FakeQdrant(_points(RERANK_POOL))
    dense, sparse = _patch_models(monkeypatch, client, hs)
    hits = hs.hybrid_search("credit risk", SearchFilters(ticker="JPM"), k=8,
                            use_reranker=False, collection="c")
    assert [h.id for h in hits] == [f"id{i}" for i in range(8)]
    assert dense.queries == [BGE_QUERY_INSTRUCTION + "credit risk"]
    assert sparse.queries == ["credit risk"]
    collection, kw = client.calls[0]
    assert collection == "c"
    assert kw["query"] == models.FusionQuery(fusion=models.Fusion.RRF)
    assert kw["limit"] == RERANK_POOL
    pre = kw["prefetch"]
    assert [p.using for p in pre] == ["dense", "sparse"]
    assert all(p.limit == RERANK_POOL for p in pre)
    assert all(p.filter == hs.build_filter(SearchFilters(ticker="JPM")) for p in pre)


def test_hybrid_dense_only(monkeypatch):
    client = FakeQdrant(_points(5))
    _, sparse = _patch_models(monkeypatch, client, hs)
    hits = hs.hybrid_search("q", SearchFilters(item="7"), k=3, use_reranker=False,
                            use_sparse=False, collection="c")
    assert len(hits) == 3
    assert sparse.queries == []
    _, kw = client.calls[0]
    assert kw["using"] == "dense" and "prefetch" not in kw
    assert kw["query_filter"] == hs.build_filter(SearchFilters(item="7"))


def test_hybrid_calls_reranker(monkeypatch):
    client = FakeQdrant(_points(RERANK_POOL))
    _patch_models(monkeypatch, client, hs)
    seen = {}

    def fake_rerank(query, hits, top_k):
        seen.update(query=query, n=len(hits), k=top_k)
        return hits[::-1][:top_k]

    monkeypatch.setattr(hs, "rerank", fake_rerank)
    hits = hs.hybrid_search("q", k=8, collection="c")
    assert seen == {"query": "q", "n": RERANK_POOL, "k": 8}
    assert hits[0].id == f"id{RERANK_POOL - 1}"


# ---- reranker -------------------------------------------------------------------------------

def test_rerank_orders_by_cross_encoder_score(monkeypatch):
    class FakeCE:
        def rerank(self, query, docs):
            return [float(d.split()[-1]) % 3 for d in docs]   # 0,1,2,0,1,...

    monkeypatch.setattr(reranker, "rerank_model", lambda: FakeCE())
    hits = [SearchHit(id=f"id{i}", score=0.0, payload={"text": f"doc {i}"}) for i in range(6)]
    out = reranker.rerank("q", hits, 3)
    assert [h.score for h in out] == [2.0, 2.0, 1.0]
    assert {h.id for h in out[:2]} == {"id2", "id5"}


def test_rerank_empty():
    assert reranker.rerank("q", [], 8) == []


# ---- indexing -------------------------------------------------------------------------------

def test_index_chunks_ids_and_payload(monkeypatch):
    client = FakeQdrant()
    _patch_models(monkeypatch, client, index_qdrant)
    monkeypatch.setattr(index_qdrant, "BATCH", 3)   # exercise several batches + remainder
    n = index_qdrant.index_chunks([FIXTURE], collection="c")
    chunks = list(read_chunks(FIXTURE))
    assert n == len(chunks) == len(client.upserted)
    for c in chunks:
        p = client.upserted[point_id(c["accession_no"], c["item"], c["chunk_index"])]
        assert p.payload == c
        assert set(p.vector) == {"dense", "sparse"}
        assert p.vector["dense"] == [float(len(c["text"]))] * 4


def test_reindex_with_fewer_chunks_drops_stale_points(monkeypatch, tmp_path):
    client = FakeQdrant()
    _patch_models(monkeypatch, client, index_qdrant)
    chunks = list(read_chunks(FIXTURE))
    nvda = [c for c in chunks if c["ticker"] == "NVDA"]
    full, shorter = tmp_path / "full.jsonl", tmp_path / "short.jsonl"
    write_chunks(full, chunks)
    write_chunks(shorter, nvda[:1])
    index_qdrant.index_chunks([full], collection="c")
    index_qdrant.index_chunks([shorter], collection="c")
    remaining = {p.payload["ticker"]: 0 for p in client.upserted.values()}
    for p in client.upserted.values():
        remaining[p.payload["ticker"]] += 1
    assert remaining["NVDA"] == 1                       # stale NVDA points removed
    assert remaining["JPM"] == sum(c["ticker"] == "JPM" for c in chunks)  # others untouched
