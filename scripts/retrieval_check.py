"""Manual retrieval check (Phase 2, AC6): is the right chunk in the top 10 for >= 16 of 20?

Each line of evals/retrieval_check.jsonl:
  {"question": ..., "filters": {SearchFilters fields} | null,
   "gold": {"ticker": ..., "fiscal_year": ..., "item": ..., "contains": [phrases]}}
A retrieved chunk is a hit when its ticker/fiscal_year/item match the gold and its text
contains every phrase (case-insensitive).

Usage: uv run python scripts/retrieval_check.py [--no-reranker] [--no-sparse]
       [--pool N] [--rerank-model NAME]
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings  # noqa: E402
from src.retrieval import hybrid_search as hs  # noqa: E402
from src.retrieval.types import SearchFilters  # noqa: E402

QUESTIONS = Path(__file__).resolve().parent.parent / "evals" / "retrieval_check.jsonl"
TOP = 10
PASS = 16


def is_hit(payload: dict, gold: dict) -> bool:
    if any(payload[k] != gold[k] for k in ("ticker", "fiscal_year", "item") if k in gold):
        return False
    text = payload["text"].lower()
    return all(p.lower() in text for p in gold.get("contains", []))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-reranker", action="store_true")
    ap.add_argument("--no-sparse", action="store_true")
    ap.add_argument("--pool", type=int, help="candidates to rerank (default RERANK_POOL)")
    ap.add_argument("--rerank-model", help="override settings.rerank_model")
    args = ap.parse_args()
    if args.pool:
        hs.RERANK_POOL = args.pool
    if args.rerank_model:
        get_settings().rerank_model = args.rerank_model

    rows = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    hits, latencies = 0, []
    hs.hybrid_search("warm up", k=1, use_reranker=not args.no_reranker)  # load models
    for i, row in enumerate(rows, 1):
        filters = SearchFilters(**row["filters"]) if row.get("filters") else None
        t0 = time.perf_counter()
        results = hs.hybrid_search(row["question"], filters, k=TOP,
                                   use_reranker=not args.no_reranker,
                                   use_sparse=not args.no_sparse)
        latencies.append(time.perf_counter() - t0)
        rank = next((r for r, h in enumerate(results, 1) if is_hit(h.payload, row["gold"])), None)
        hits += rank is not None
        print(f"{i:2}. {'HIT ' if rank else 'MISS'} rank={rank or '-':>2} "
              f"{latencies[-1]:5.2f}s  {row['question']}")
        if rank is None and results:
            top = results[0].payload
            print(f"      top1: {top['ticker']} FY{top['fiscal_year']} Item {top['item']} "
                  f"| {top['section'][:70]}")
    p50 = statistics.median(latencies)
    p95 = sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)]
    print(f"\n{hits}/{len(rows)} in top {TOP} (pass: >= {PASS}) | "
          f"latency p50 {p50:.2f}s p95 {p95:.2f}s | reranker={not args.no_reranker} "
          f"model={get_settings().rerank_model} pool={hs.RERANK_POOL} sparse={not args.no_sparse}")
    return 0 if hits >= PASS else 1


if __name__ == "__main__":
    sys.exit(main())
