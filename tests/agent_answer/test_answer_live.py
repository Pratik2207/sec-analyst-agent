"""Live answer writer on Ollama (settings.answer_model). At most 4 LLM calls in total.

Run: uv run pytest tests/agent_answer -m integration -s   (prints answers and latency)
"""

import time

import pytest

from src.agent.answerer import answer
from src.agent.evidence import render_answer, resolve
from src.agent.verifier import feedback_text, verify
from tests.agent_answer.fixtures import MULTIHOP_QUESTION, NVDA_GM_CHUNK, facts, multihop

pytestmark = pytest.mark.integration


def _run(question, results, feedback=None):
    t0 = time.perf_counter()
    draft, tokens = answer(question, results, feedback=feedback)
    secs = time.perf_counter() - t0
    print(f"\nQ: {question}\n  {secs:.1f}s, tokens {tokens.prompt}+{tokens.completion}, "
          f"not_found={draft.not_found}")
    for c in draft.claims:
        print(f"  - {c.text}  {c.source_ids}")
    return draft


def _check_cited(draft, results):
    vr = verify(draft, results)
    for c, reason in vr.failed_claims:
        print(f"  FAILED: {c.text} -> {reason}")
    return vr


@pytest.fixture
def ctx_8k(monkeypatch):
    """The multi-hop evidence (~3.6k prompt tokens) plus verifier feedback exceeds Ollama's
    default 4096-token context, and llm.chat_json (contract) sets no num_ctx. Until the
    contract sets it, emulate options num_ctx=8192 here."""
    import ollama
    chat = ollama.Client.chat

    def chat_8k(self, *args, options=None, **kw):
        return chat(self, *args, options={**(options or {}), "num_ctx": 8192}, **kw)
    monkeypatch.setattr(ollama.Client, "chat", chat_8k)


@pytest.mark.usefixtures("ctx_8k")
def test_multihop_claims_verify_and_resolve():
    results = multihop()
    draft = _run(MULTIHOP_QUESTION, results)
    assert not draft.not_found and draft.claims
    vr = _check_cited(draft, results)
    if vr.failed_claims:   # the graph's one re-answer (FR-13)
        draft = _run(MULTIHOP_QUESTION, results, feedback=feedback_text(vr))
        vr = _check_cited(draft, results)
    assert draft.claims and not vr.failed_claims
    for c in vr.ok_claims:
        cites = resolve(c.source_ids, results)
        assert cites and all(x.url.startswith("https://www.sec.gov/") for x in cites), c
    text, cites = render_answer(vr.ok_claims, results)
    print(f"  ANSWER: {text}\n  " + "\n  ".join(f"[{i}] {c.ticker} FY{c.fiscal_year} {c.url}"
                                                for i, c in enumerate(cites, 1)))
    # Only INTC meets both conditions in the fixture (R&D share +2.51 pts, margin -1.19 pts).
    assert "INTC" in text or "Intel" in text
    # The others' R&D share fell; a claim saying it rose is a wrong conclusion.
    others = [c.text for c in vr.ok_claims if "R&D" in c.text
              and any(t in c.text for t in ("NVDA", "NVIDIA", "AMD", "QCOM", "Qualcomm"))]
    assert not any(w in t for t in others for w in ("raised", "increased", "rose")), others


def test_nvda_gross_margin_from_chunk():
    results = [facts(["NVDA"], [2025]), NVDA_GM_CHUNK]
    draft = _run("What was NVIDIA's gross margin in fiscal 2025?", results)
    assert not draft.not_found
    vr = _check_cited(draft, results)
    assert not vr.failed_claims and any("75" in c.text for c in vr.ok_claims)


def test_question_outside_evidence_is_not_found():
    draft = _run("What was NVIDIA's revenue in FY2030?", [facts(["NVDA"])])
    assert draft.not_found


def test_empty_evidence_is_not_found_without_call():
    draft = _run("What was NVIDIA's revenue in FY2030?", [])
    assert draft.not_found and draft.claims == []
