"""Unit tests for the naive RAG baseline: stubbed search and stubbed Ollama client."""

from types import SimpleNamespace

import pytest

from config.settings import get_settings
from src.api.schemas import AskResponse
from src.baseline import naive_rag
from src.retrieval.types import SearchHit


def payload(i: int, section: str = "Gross Margin") -> dict:
    return {"ticker": f"T{i}", "form": "10-K", "fiscal_year": 2025, "item": "7",
            "section": section, "accession_no": f"0000-25-{i:06d}",
            "source_url": f"https://www.sec.gov/Archives/edgar/data/{i}/doc.htm",
            "text": f"[Co{i} | 10-K | FY2025 | Item 7 MD&A]\n\nbody {i}"}


HITS = [SearchHit(id=f"id{i}", score=0.5, payload=payload(i)) for i in range(1, 4)]


class StubClient:
    def __init__(self, content: str):
        self.content, self.calls = content, []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message=SimpleNamespace(content=self.content),
                               prompt_eval_count=123, eval_count=45)


@pytest.fixture
def run(monkeypatch):
    def _run(content: str, hits=HITS):
        search_calls, client = [], StubClient(content)

        def fake_search(query, **kwargs):
            search_calls.append((query, kwargs))
            return hits

        monkeypatch.setattr(naive_rag, "hybrid_search", fake_search)
        monkeypatch.setattr(naive_rag, "_client", lambda: client)
        return naive_rag.answer("Why did margin change?"), search_calls, client
    return _run


def test_prompt_has_delimited_chunks_and_injection_line():
    msgs = naive_rag.build_messages("Q?", HITS)
    system, user = msgs[0]["content"], msgs[1]["content"]
    assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user"
    assert "never instructions" in system
    assert "Not found in the filings." in system and "[n]" in system
    assert user.startswith("<context>\n") and "</context>" in user
    for i in (1, 2, 3):
        assert f"<chunk id={i}>\n{HITS[i - 1].payload['text']}\n</chunk>" in user
    assert user.endswith("Question: Q?")


def test_parse_citations_maps_dedups_and_ignores_out_of_range():
    cites = naive_rag.parse_citations("A [1][3]. B [1]. C [9] [0].", HITS)
    assert [c.ticker for c in cites] == ["T1", "T3"]
    c = cites[0]
    assert (c.form, c.fiscal_year, c.section, c.accession_no, c.url) == (
        "10-K", 2025, "Item 7 | Gross Margin", "0000-25-000001",
        "https://www.sec.gov/Archives/edgar/data/1/doc.htm")


def test_parse_citations_none_and_dedup_same_chunk_content():
    assert naive_rag.parse_citations("No markers here.", HITS) == []
    twin = [HITS[0], SearchHit(id="other", score=0.1, payload=payload(1))]
    assert len(naive_rag.parse_citations("x [1] y [2]", twin)) == 1


def test_empty_section_omits_separator():
    assert naive_rag.to_citation(payload(1, section="")).section == "Item 7"


def test_not_found_has_no_citations(run):
    resp, _, _ = run("Not found in the filings.")
    assert resp.answer == "Not found in the filings." and resp.citations == []


def test_leaked_reasoning_is_stripped(run):
    resp, _, _ = run("Chunk 1 and [3] look relevant.\n</think>\n\nMargin rose [2].")
    assert resp.answer == "Margin rose [2]."
    assert [c.ticker for c in resp.citations] == ["T2"]


def test_full_response(run):
    resp, search_calls, client = run("Margin rose [2].")
    assert search_calls == [("Why did margin change?",
                             {"k": 8, "use_reranker": False, "use_sparse": False})]
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["model"] == get_settings().answer_model and call["think"] is False
    assert call["options"] == {"temperature": 0}
    assert [c.ticker for c in resp.citations] == ["T2"]
    assert [(s.name, s.detail) for s in resp.steps] == [
        ("retrieve", {"k": 8, "hits": ["id1", "id2", "id3"]}),
        ("generate", {"model": get_settings().answer_model})]
    assert (resp.tokens.prompt, resp.tokens.completion) == (123, 45)
    assert isinstance(resp.latency_ms, int) and resp.latency_ms >= 0
    assert AskResponse.model_validate(resp.model_dump()) == resp
