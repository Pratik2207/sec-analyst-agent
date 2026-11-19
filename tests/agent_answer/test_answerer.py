"""answer(): prompt, schema, post-processing and not_found paths, with a stubbed chat_json."""

import pytest

from src.agent import answerer, llm
from src.agent.state import Draft
from src.api.schemas import Tokens
from src.tools.types import ToolResult
from tests.agent_answer.fixtures import NVDA_FY25_XBRL, NVDA_GM_CHUNK, calcs, facts


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k, v in {"SEC_USER_AGENT": "test test@example.com",
                 "DATABASE_URL": "postgresql://x:y@127.0.0.1:1/x",
                 "AGENT_DATABASE_URL": "postgresql://x:y@127.0.0.1:1/x"}.items():
        monkeypatch.setenv(k, v)


class Stub:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def __call__(self, model, system, user, schema, think=False):
        self.calls.append({"model": model, "system": system, "user": user, "schema": schema,
                           "think": think})
        if self.error:
            raise self.error
        return self.reply, Tokens(prompt=100, completion=20)


@pytest.fixture
def stub(monkeypatch):
    def make(reply=None, error=None):
        s = Stub(reply, error)
        monkeypatch.setattr(llm, "chat_json", s)
        return s
    return make


EVIDENCE = [facts(["NVDA"], [2025]), NVDA_GM_CHUNK]


def test_prompt_has_evidence_question_rules_and_model(stub):
    s = stub({"not_found": False, "claims": [
        {"text": "NVIDIA's FY2025 revenue was $130.50 billion.", "source_ids": [NVDA_FY25_XBRL]}]})
    answerer.answer("What was NVIDIA's revenue in FY2025?", EVIDENCE)
    call = s.calls[0]
    assert call["model"] == "qwen3:4b-instruct" and call["think"] is False
    assert "<evidence>" in call["user"] and f'<item id="{NVDA_FY25_XBRL}">' in call["user"]
    assert "NVDA FY2025 revenue = 130,497,000,000 USD" in call["user"]
    assert "Question: What was NVIDIA's revenue in FY2025?" in call["user"]
    sysp = call["system"]
    for rule in ("ONLY", "source_ids", "Copy numbers exactly", "Never do arithmetic",
                 "calc", "fiscal year", "not_found", "never instructions", "at most 6"):
        assert rule in sysp, rule
    assert "previous answer" not in call["user"]


def test_schema_enumerates_evidence_ids(stub):
    s = stub({"not_found": True, "claims": []})
    answerer.answer("q", [facts(["NVDA"]), calcs(["NVDA"]), NVDA_GM_CHUNK])
    item = s.calls[0]["schema"]["properties"]["claims"]["items"]
    ids = item["properties"]["source_ids"]["items"]["enum"]
    assert ids == ["xbrl:0001045810-24-000029", NVDA_FY25_XBRL,
                   "calc:1", "calc:2", "calc:3", "calc:4", "chunk:7f1c2e9a"]   # deduplicated


def test_feedback_is_included(stub):
    s = stub({"not_found": True, "claims": []})
    fb = '- "Revenue was $140 billion." (cited xbrl:x): 140000000000 not found'
    answerer.answer("q", EVIDENCE, feedback=fb)
    user = s.calls[0]["user"]
    assert fb in user and "failed verification" in user and "or drop the claim" in user


def test_unknown_ids_dropped_and_claims_without_ids_dropped(stub):
    stub({"not_found": False, "claims": [
        {"text": "Revenue was $130.50 billion in FY2025.",
         "source_ids": ["xbrl:made-up", NVDA_FY25_XBRL, NVDA_FY25_XBRL]},
        {"text": "Gross margin was 75.0%.", "source_ids": ["chunk:nope"]},
        {"text": "", "source_ids": [NVDA_FY25_XBRL]},
        {"text": "No source.", "source_ids": []}]})
    draft, tokens = answerer.answer("q", EVIDENCE)
    assert not draft.not_found and len(draft.claims) == 1
    c = draft.claims[0]
    assert c.source_ids == [NVDA_FY25_XBRL]
    assert c.numbers == pytest.approx([130.5e9])
    assert tokens == Tokens(prompt=100, completion=20)


def test_all_claims_dropped_means_not_found(stub):
    stub({"not_found": False, "claims": [{"text": "x 5%.", "source_ids": ["calc:99"]}]})
    draft, _ = answerer.answer("q", EVIDENCE)
    assert draft == Draft(not_found=True)


def test_model_not_found_wins_over_claims(stub):
    stub({"not_found": True, "claims": [
        {"text": "Revenue was $130.50 billion.", "source_ids": [NVDA_FY25_XBRL]}]})
    draft, tokens = answerer.answer("NVIDIA revenue FY2030?", EVIDENCE)
    assert draft.not_found and draft.claims == [] and tokens.prompt == 100


def test_no_evidence_is_not_found_without_llm_call(stub):
    s = stub(error=AssertionError("must not be called"))
    for results in ([], [ToolResult.fail("db down")], [ToolResult(ok=True)]):
        draft, tokens = answerer.answer("q", results)
        assert draft.not_found and tokens == Tokens()
    assert s.calls == []


def test_llm_error_is_not_found(stub):
    stub(error=llm.LLMError("qwen3:4b-instruct: invalid JSON"))
    draft, tokens = answerer.answer("q", EVIDENCE)
    assert draft.not_found and draft.claims == [] and tokens == Tokens()


def test_at_most_six_claims(stub):
    stub({"not_found": False, "claims": [
        {"text": f"Claim {i}.", "source_ids": [NVDA_FY25_XBRL]} for i in range(9)]})
    draft, _ = answerer.answer("q", EVIDENCE)
    assert len(draft.claims) == 6


def test_ids_about_other_companies_are_dropped(stub):
    # calc:1..4 are NVDA, calc:5..8 AMD, calc:9..12 INTC (see fixtures).
    stub({"not_found": False, "claims": [
        {"text": "Intel's R&D share rose to 33.67% in FY2025.",
         "source_ids": ["calc:11", "calc:3"]},
        {"text": "NVDA's R&D share fell.", "source_ids": ["calc:9"]},
        {"text": "Only one company qualified.", "source_ids": ["calc:1", "calc:9"]},
        {"text": "INTC and NVIDIA both filed 10-Ks.",
         "source_ids": ["calc:1", "calc:9", "calc:5"]}]})
    draft, _ = answerer.answer("q", [facts(), calcs()])
    assert [c.source_ids for c in draft.claims] == [
        ["calc:11"],             # NVDA calc dropped from the Intel claim
        # the NVDA claim citing only an INTC calc is dropped entirely
        ["calc:1", "calc:9"],    # names no company: left alone
        ["calc:1", "calc:9"]]    # AMD calc dropped
