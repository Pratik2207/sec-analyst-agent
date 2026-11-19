"""Live baseline: real Qdrant `filings` collection (read-only) + Ollama answer model."""

import pytest

from src.baseline import naive_rag

pytestmark = pytest.mark.integration

QUESTIONS = [
    "Why did NVIDIA's gross margin change in fiscal 2025?",
    "What supply chain risks does Intel describe in its 10-K?",
    "How does JPMorgan Chase describe its exposure to credit risk?",
]


@pytest.mark.parametrize("question", QUESTIONS)
def test_live_answer_has_sec_citations(question):
    resp = naive_rag.answer(question)
    print(f"\n{question}\n{resp.latency_ms} ms {resp.tokens}\n{resp.answer}\n{resp.citations}")
    assert resp.answer.strip()
    assert len(resp.citations) >= 1
    assert all(c.url.startswith("https://www.sec.gov/") for c in resp.citations)
