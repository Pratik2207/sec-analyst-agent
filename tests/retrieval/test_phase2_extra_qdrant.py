"""Phase 2 integration: real fastembed models + docker Qdrant.

- Full ingest of 2 real pilot filings into a throwaway `test_` collection: idempotent
  re-index, stale-point removal, both vectors, filtered hybrid search.
- Read-only checks (count / retrieve / search only) on the real `filings` collection.
"""

import uuid
from collections import Counter

import pytest
from qdrant_client import models

from config.settings import get_settings
from src.ingest.chunk_schema import CHUNKS_DIR, point_id, read_chunks, write_chunks
from src.ingest.index_qdrant import index_chunks
from src.retrieval.hybrid_search import hybrid_search
from src.retrieval.models import qdrant
from src.retrieval.types import SearchFilters

pytestmark = pytest.mark.integration

NVDA_FY23 = CHUNKS_DIR / "0001045810-23-000017.jsonl"
LLY_FY23 = CHUNKS_DIR / "0000059478-24-000065.jsonl"
REAL = get_settings().qdrant_collection


def _reachable():
    try:
        qdrant().get_collections()
    except Exception as e:
        pytest.skip(f"qdrant not reachable: {e}")


def _count(collection, **match):
    flt = models.Filter(must=[models.FieldCondition(key=k, match=models.MatchValue(value=v))
                              for k, v in match.items()]) if match else None
    return qdrant().count(collection, count_filter=flt, exact=True).count


# ---- throwaway collection with 2 real filings -------------------------------------------------

@pytest.fixture(scope="module")
def two_filings():
    _reachable()
    if not (NVDA_FY23.exists() and LLY_FY23.exists()):
        pytest.skip("real chunk files missing")
    name = f"test_phase2_{uuid.uuid4().hex[:8]}"
    n = index_chunks([NVDA_FY23, LLY_FY23], collection=name)
    try:
        yield name, n
    finally:
        qdrant().delete_collection(name)
    assert not qdrant().collection_exists(name)


def test_ingest_two_real_filings_counts(two_filings):
    name, n = two_filings
    nvda, lly = list(read_chunks(NVDA_FY23)), list(read_chunks(LLY_FY23))
    assert n == len(nvda) + len(lly) == _count(name)
    assert _count(name, ticker="NVDA") == len(nvda)
    assert _count(name, ticker="LLY") == len(lly)


def test_collection_schema(two_filings):
    name, _ = two_filings
    info = qdrant().get_collection(name)
    dense = info.config.params.vectors["dense"]
    assert dense.size == get_settings().embed_dim and dense.distance == models.Distance.COSINE
    assert info.config.params.sparse_vectors["sparse"].modifier == models.Modifier.IDF
    schema = info.payload_schema
    for f in ("ticker", "sector", "item"):
        assert schema[f].data_type == models.PayloadSchemaType.KEYWORD
    assert schema["fiscal_year"].data_type == models.PayloadSchemaType.INTEGER


def test_reindex_same_files_is_idempotent(two_filings):
    name, _ = two_filings
    before = _count(name)
    index_chunks([NVDA_FY23, LLY_FY23], collection=name)
    assert _count(name) == before


def test_points_payload_and_vectors(two_filings):
    name, _ = two_filings
    c = next(read_chunks(NVDA_FY23))
    (p,) = qdrant().retrieve(name, [point_id(c["accession_no"], c["item"], c["chunk_index"])],
                             with_payload=True, with_vectors=True)
    assert p.payload == c
    assert len(p.vector["dense"]) == get_settings().embed_dim
    assert len(p.vector["sparse"].indices) > 0


@pytest.mark.parametrize("filters, field, allowed", [
    (SearchFilters(ticker="NVDA"), "ticker", {"NVDA"}),
    (SearchFilters(sector="pharma"), "sector", {"pharma"}),
    (SearchFilters(fiscal_year=2023), "fiscal_year", {2023}),
    (SearchFilters(item="1A"), "item", {"1A"}),
    (SearchFilters(item=["7", "7A"]), "item", {"7", "7A"}),
])
def test_filtered_hybrid_search_no_rerank(two_filings, filters, field, allowed):
    name, _ = two_filings
    hits = hybrid_search("risks to revenue growth", filters, k=8, use_reranker=False,
                         collection=name)
    assert len(hits) == 8
    assert {h.payload[field] for h in hits} <= allowed


def test_stale_points_removed_when_filing_rechunks_shorter(two_filings, tmp_path):
    name, _ = two_filings
    nvda = list(read_chunks(NVDA_FY23))
    shorter = tmp_path / NVDA_FY23.name
    write_chunks(shorter, nvda[:10])
    lly_before = _count(name, ticker="LLY")
    try:
        index_chunks([shorter], collection=name)
        assert _count(name, ticker="NVDA") == 10
        assert _count(name, ticker="LLY") == lly_before
    finally:
        index_chunks([NVDA_FY23], collection=name)   # restore for later tests
    assert _count(name, ticker="NVDA") == len(nvda)


# ---- read-only checks on the real `filings` collection ----------------------------------------

@pytest.fixture(scope="module")
def real():
    _reachable()
    if not qdrant().collection_exists(REAL):
        pytest.skip(f"{REAL} collection missing")
    return REAL


def test_real_collection_matches_chunk_files_exactly(real):
    files = sorted(CHUNKS_DIR.glob("*.jsonl"))
    per_file = {p.stem: sum(1 for _ in read_chunks(p)) for p in files}
    assert _count(real) == sum(per_file.values())
    for acc, n in per_file.items():
        assert _count(real, accession_no=acc) == n, acc


def test_real_points_have_dense_and_sparse(real):
    chunks = list(read_chunks(NVDA_FY23))[::40]
    ids = [point_id(c["accession_no"], c["item"], c["chunk_index"]) for c in chunks]
    pts = qdrant().retrieve(real, ids, with_payload=True, with_vectors=True)
    assert len(pts) == len(ids)
    for p in pts:
        assert set(p.vector) == {"dense", "sparse"}
        assert len(p.vector["sparse"].indices) > 0


@pytest.mark.parametrize("filters, check", [
    (SearchFilters(ticker="JPM"), lambda p: p["ticker"] == "JPM"),
    (SearchFilters(ticker=["NVDA", "AMD"]), lambda p: p["ticker"] in {"NVDA", "AMD"}),
    (SearchFilters(sector="banks"), lambda p: p["sector"] == "banks"),
    (SearchFilters(fiscal_year=2024), lambda p: p["fiscal_year"] == 2024),
    (SearchFilters(fiscal_year=[2023, 2025]), lambda p: p["fiscal_year"] in {2023, 2025}),
    (SearchFilters(item="7"), lambda p: p["item"] == "7"),
    (SearchFilters(ticker="NVDA", fiscal_year=2025, item="1A"),
     lambda p: (p["ticker"], p["fiscal_year"], p["item"]) == ("NVDA", 2025, "1A")),
])
def test_real_filters_no_rerank(real, filters, check):
    hits = hybrid_search("revenue growth and competition", filters, k=8,
                         use_reranker=False, collection=real)
    assert len(hits) == 8
    assert all(check(h.payload) for h in hits)


def test_real_sector_values_exist(real):
    sectors = Counter()
    for s in ("semiconductors", "banks", "pharma"):
        sectors[s] = _count(real, sector=s)
    assert all(v > 0 for v in sectors.values()), sectors


def test_real_reranked_search_returns_8_sorted(real):
    hits = hybrid_search("NVIDIA data center revenue growth", SearchFilters(ticker="NVDA"),
                         collection=real)
    assert len(hits) == 8
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)
    assert all(h.payload["ticker"] == "NVDA" for h in hits)
