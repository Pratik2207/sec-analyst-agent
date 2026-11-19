"""Router accuracy with the real fast model (qwen3:1.7b via Ollama). Needs Ollama only."""

import statistics
import time

import httpx
import pytest

from src.agent import router
from tests.agent_fast.test_router import CASES

pytestmark = pytest.mark.integration

SEMIS = ("Which semiconductor companies raised R&D as a share of revenue while gross margin "
         "fell, FY2024 to FY2025?")


def test_router_accuracy_on_fixture_set(monkeypatch):
    try:
        httpx.get(router.get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")
    monkeypatch.setattr(router, "KEEP_ALIVE", "1m")
    results, latencies = {}, []
    for c in CASES:
        t = time.perf_counter()
        r = router.route(c["q"])
        latencies.append(time.perf_counter() - t)
        ok = r.kind == c["kind"] and (c["kind"] == "agent" or r.query == router.FactQuery(
            c["ticker"], c["metric"], c["fiscal_year"]))
        results[c["q"]] = ok
        print(f"{'OK ' if ok else 'BAD'} {r.kind:5} {c['q'][:70]!r} -- {r.reason}")
    accuracy = sum(results.values()) / len(results)
    print(f"accuracy {accuracy:.0%} ({sum(results.values())}/{len(results)}), "
          f"p50 routing latency {statistics.median(latencies) * 1000:.0f} ms, "
          f"max {max(latencies) * 1000:.0f} ms")
    assert results["What was Intel's R&D in FY2024?"]
    assert results[SEMIS]
    assert accuracy >= 0.9
