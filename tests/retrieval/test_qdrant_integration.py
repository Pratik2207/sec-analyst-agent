"""Index the fixture chunks into a throwaway `test_` Qdrant collection and search it.

Needs Qdrant on settings.qdrant_url and downloads the fastembed models on first run.
"""

import uuid
from pathlib import Path

import pytest

from src.ingest.chunk_schema import point_id, read_chunks
from src.ingest.index_qdrant import index_chunks
from src.retrieval.hybrid_search import hybrid_search
from src.retrieval.models import qdrant
from src.retrieval.types import SearchFilters

pytestmark = pytest.mark.integration

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "chunks_sample.jsonl"
CHUNKS = list(read_chunks(FIXTURE))


@pytest.fixture(scope="module")
def collection():
    try:
        qdrant().get_collections()
    except Exception as e:  # connection refused etc.
        pytest.skip(f"qdrant not reachable: {e}")
    name = f"test_track_b_{uuid.uuid4().hex[:8]}"
    index_chunks([FIXTURE], collection=name)
    yield name
    qdrant().delete_collection(name)


def test_reindex_is_idempotent_and_ids_deterministic(collection):
    client = qdrant()
    before = client.count(collection, exact=True).count
    assert before == len(CHUNKS)
    assert index_chunks([FIXTURE], collection=collection) == len(CHUNKS)
    assert client.count(collection, exact=True).count == before
    ids = {str(p.id) for p in client.scroll(collection, limit=100)[0]}
    assert ids == {point_id(c["accession_no"], c["item"], c["chunk_index"]) for c in CHUNKS}


def test_points_have_dense_and_sparse(collection):
    p = qdrant().scroll(collection, limit=1, with_vectors=True)[0][0]
    assert set(p.vector) == {"dense", "sparse"}
    assert len(p.vector["dense"]) == 384


@pytest.mark.parametrize("use_reranker", [True, False])
@pytest.mark.parametrize("use_sparse", [True, False])
def test_nvidia_gross_margin_first(collection, use_reranker, use_sparse):
    hits = hybrid_search("NVIDIA gross margin", collection=collection,
                         use_reranker=use_reranker, use_sparse=use_sparse)
    assert hits[0].payload["ticker"] == "NVDA"
    assert hits[0].payload["section"] == "Gross Margin"
    assert len(hits) == len(CHUNKS)          # fewer than k=8 exist; all are returned
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_k_limits_results(collection):
    assert len(hybrid_search("research and development", k=3, collection=collection)) == 3


def test_jpm_credit_risk_filtered(collection):
    hits = hybrid_search("JPMorgan credit risk", SearchFilters(ticker="JPM"),
                         collection=collection)
    assert hits and {h.payload["ticker"] for h in hits} == {"JPM"}
    assert hits[0].payload["section"] == "Credit Risk"


@pytest.mark.parametrize("filters, field, allowed", [
    (SearchFilters(ticker="PFE"), "ticker", {"PFE"}),
    (SearchFilters(ticker=["PFE", "JPM"]), "ticker", {"PFE", "JPM"}),
    (SearchFilters(sector="semiconductors"), "sector", {"semiconductors"}),
    (SearchFilters(sector=["banks", "pharma"]), "sector", {"banks", "pharma"}),
    (SearchFilters(fiscal_year=2025), "fiscal_year", {2025}),
    (SearchFilters(fiscal_year=[2024]), "fiscal_year", {2024}),
    (SearchFilters(item="1A"), "item", {"1A"}),
    (SearchFilters(item=["1", "1A"]), "item", {"1", "1A"}),
])
def test_filters(collection, filters, field, allowed):
    hits = hybrid_search("research and development expenses", filters, collection=collection)
    expected = sum(1 for c in CHUNKS if c[field] in allowed)
    assert len(hits) == expected > 0
    assert {h.payload[field] for h in hits} <= allowed


def test_combined_filters(collection):
    hits = hybrid_search("risk", SearchFilters(ticker="NVDA", item="1A", fiscal_year=2025),
                         collection=collection)
    assert [h.payload["section"] for h in hits] == [
        "Competition could adversely impact our market share and financial results"]


def test_no_match_returns_empty(collection):
    assert hybrid_search("anything", SearchFilters(ticker="NOPE"), collection=collection) == []
