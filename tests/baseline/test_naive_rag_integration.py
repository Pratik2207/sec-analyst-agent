"""Live baseline: real Qdrant `filings` collection (read-only) + Ollama answer model."""

import pytest

from src.baseline import naive_rag

pytestmark = pytest.mark.integration

# Observed: on long list-style answers qwen3:4b writes "Chunks 1, 2, and 3" instead of
# [n] markers, so the naive baseline yields no citations there. Kept visible as xfail.
NO_MARKERS = pytest.mark.xfail(reason="qwen3:4b omits [n] markers on long answers",
                               strict=False)
QUESTIONS = [
    "Why did NVIDIA's gross margin change in fiscal 2025?",
    pytest.param("What supply chain risks does Intel describe in its 10-K?", marks=NO_MARKERS),
    pytest.param("How does JPMorgan Chase describe its exposure to credit risk?",
                 marks=NO_MARKERS),
]


@pytest.mark.parametrize("question", QUESTIONS)
def test_live_answer_has_sec_citations(question):
    resp = naive_rag.answer(question)
    print(f"\n{question}\n{resp.latency_ms} ms {resp.tokens}\n{resp.answer}\n{resp.citations}")
    assert resp.answer.strip()
    assert len(resp.citations) >= 1
    assert all(c.url.startswith("https://www.sec.gov/") for c in resp.citations)
