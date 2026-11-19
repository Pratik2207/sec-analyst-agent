"""Deterministic scorers: numbers, refusal, citations, recall, latency."""

import pytest

from evals.schema import DatasetItem, GoldSource
from evals.scoring.citations import citation_score
from evals.scoring.latency import percentile, summarize
from evals.scoring.numbers import number_correct
from evals.scoring.recall import first_hit_rank, is_hit
from evals.scoring.refusal import is_refusal
from src.agent.fast_path import NOT_FOUND
from src.api.schemas import Citation

# ---- numbers ----------------------------------------------------------------------------


@pytest.mark.parametrize("answer", [
    "Intel's R&D expense in FY2024 was $16.55 billion.",
    "R&D was $16,546 million [1].",
    "R&D was $16.5 billion.",                      # 0.3% off
    "R&D expense: 16,546,000,000 USD",
    "R&D (in millions): 16,546",                   # unit dropped, table scale
    "In FY2024 (period ending 2024-12-28) R&D was $16.55B.",
])
def test_usd_scale_aware_within_1pct(answer):
    assert number_correct(answer, 16_546_000_000.0, "USD")


@pytest.mark.parametrize("answer", [
    "R&D was $16.2 billion.",                      # 2% off
    "R&D was $18 billion in 2024.",
    "Not found in the filings.",
    "R&D grew in FY2024.",                         # the year is not a number
])
def test_usd_wrong(answer):
    assert not number_correct(answer, 16_546_000_000.0, "USD")


def test_percent_and_pp_direct_and_magnitude():
    assert number_correct("Gross margin was 75.0%.", 75.03, "%")
    assert number_correct("Gross margin decreased by 4.34 percentage points.", -4.34, "pp")
    assert number_correct("The change was -4.34 pp.", -4.34, "pp")
    assert not number_correct("Gross margin was 0.75.", 75.0, "%")   # no scaling for %
    assert not number_correct("It fell 4.5 points.", -4.34, "pp")


def test_negative_usd_change_magnitude():
    assert number_correct("Net income decreased by $2.1 billion.", -2_100_000_000, "USD")


def test_computed_suffix_ignored():
    # only the number in "(computed: ...)" would match; it must not count
    assert not number_correct("Ratio = 9 (computed: 16546 / 1)", 16546, "USD")


# ---- refusal ----------------------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    NOT_FOUND, "not found in the filings.", "",
    "The filings do not provide NVIDIA's revenue for FY2030.",
    "There is no information about FY2030 revenue in the provided context.",
    "I cannot determine this from the filings.",
    "The context does not contain this figure. It covers FY2023-FY2025.",
])
def test_refusals(answer):
    assert is_refusal(answer)


@pytest.mark.parametrize("answer", [
    "NVIDIA's FY2025 revenue was $130.50 billion.",
    "Revenue was $130.5 billion. Segment detail is not disclosed.",   # refusal after answer
])
def test_not_refusals(answer):
    assert not is_refusal(answer)


# ---- citations --------------------------------------------------------------------------

def _cit(ticker, fy):
    return Citation(ticker=ticker, form="10-K", fiscal_year=fy, section="Item 7",
                    accession_no="x", url="u")


def _item(**kw):
    base = {"id": "q", "type": "text", "question": "q?", "gold_answer": "a"}
    return DatasetItem.model_validate({**base, **kw})


def test_citation_score():
    it = _item(gold_sources=[GoldSource(ticker="NVDA", fiscal_year=2025, item="7")])
    assert citation_score([_cit("NVDA", 2025)], it) == 1.0
    assert citation_score([_cit("NVDA", 2025), _cit("NVDA", 2024)], it) == 0.5
    assert citation_score([_cit("nvda", 2025), _cit("AMD", 2025)], it) == 0.5
    assert citation_score([], it) is None                     # no citations: not scored
    assert citation_score([_cit("NVDA", 2025)], _item()) is None   # no gold sources


# ---- recall -----------------------------------------------------------------------------

def test_recall_hit_rules():
    it = _item(gold_sources=[GoldSource(ticker="NVDA", fiscal_year=2025, item="7")],
               gold_contains=["gross margin", "Data Center"])
    good = {"ticker": "NVDA", "fiscal_year": 2025, "item": "7",
            "text": "Gross  margin rose on a higher mix of data center revenue."}
    assert is_hit(good, it)
    assert not is_hit({**good, "item": "1A"}, it)
    assert not is_hit({**good, "fiscal_year": 2024}, it)
    assert not is_hit({**good, "ticker": "AMD"}, it)
    assert not is_hit({**good, "text": "Gross margin rose."}, it)   # missing a phrase
    any_item = _item(gold_sources=[GoldSource(ticker="NVDA", fiscal_year=2025)],
                     gold_contains=["gross margin"])
    assert is_hit({**good, "item": "1A"}, any_item)                  # item not given
    other = {"ticker": "AMD", "fiscal_year": 2025, "item": "7", "text": "x"}
    assert first_hit_rank([other, other, good], it) == 3
    assert first_hit_rank([other] * 10 + [good], it) is None         # beyond top 10


# ---- latency ----------------------------------------------------------------------------

def test_percentiles():
    assert percentile([], 50) is None
    assert percentile([3.0], 95) == 3.0
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile(list(range(1, 101)), 95) == pytest.approx(95.05)
    assert percentile([5, 1, 3], 50) == 3
    s = summarize([1.0, 2.0, 3.0], [100, 200])
    assert s == {"n": 3, "p50_s": 2.0, "p95_s": pytest.approx(2.9), "tokens_mean": 150}


# ---- Phase 5 code-review fixes -------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    "I could not find NVIDIA FY2030 revenue in the filings.",
    "The context doesn't mention FY2030 revenue.",
    "No FY2030 data is available in the provided filings.",
    "Sorry, that information isn't available.",
    "The answer is not in the provided context.",
    "FY2030 revenue is not yet available.",
])
def test_review_refusal_paraphrases(answer):
    from evals.scoring.refusal import is_refusal
    assert is_refusal(answer)


def test_answer_with_number_is_not_a_refusal():
    from evals.scoring.refusal import is_refusal
    assert not is_refusal("Intel did not report a gross profit line; its gross margin was 32.7% "
                          "in FY2024.")


def test_negative_usd_gold_needs_loss_wording_and_percent_never_matches_usd():
    from evals.scoring.numbers import number_correct
    assert not number_correct("Intel's net income was $18.76 billion.", -18.756e9, "USD")
    assert number_correct("Intel had a net loss of $18.76 billion.", -18.756e9, "USD")
    assert not number_correct("Net margin was 17.1%.", 17.12e9, "USD")


def test_no_sql_ablation_forces_agent_route(monkeypatch):
    from evals import systems
    from src.agent import fast_path, graph, router
    from src.agent.router import FactQuery, Route
    from src.api.schemas import AskResponse, Tokens

    monkeypatch.setattr(router, "route", lambda q: Route("fast", FactQuery("INTC", "revenue",
                                                                            2024)))
    monkeypatch.setattr(fast_path, "answer", lambda *a: pytest.fail("fast path used"))
    monkeypatch.setattr(graph, "run_agent_traced", lambda q: (AskResponse(
        answer="x", citations=[], steps=[], tokens=Tokens(), latency_ms=0), []))
    with systems.settings_override(agent_disabled_tools=["sql_query"]):
        rr = systems.agent_system("What was Intel's revenue in FY2024?")
    assert rr.error is None and rr.route == "agent"


@pytest.mark.parametrize("bad", ["../x", "num-001/../../y", "a.b", "a b", "-x"])
def test_dataset_ids_are_path_safe(bad):
    from evals.schema import DatasetItem
    with pytest.raises(ValueError):
        DatasetItem(id=bad, type="number", question="q", gold_answer="a")
