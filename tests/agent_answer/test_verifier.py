"""verify(): code-only number check of every claim against its cited sources (FR-13, AC4)."""

import pytest

from src.agent.state import Claim, Draft
from src.agent.verifier import checked_numbers, feedback_text, verify
from tests.agent_answer.fixtures import NVDA_FY25_XBRL, NVDA_GM_CHUNK, calcs, facts

RESULTS = [facts(), calcs(), NVDA_GM_CHUNK]
# calcs() numbering: NVDA calc:1..4 (rd_share_2024, gross_margin_2024, rd_share_2025,
# gross_margin_2025), AMD calc:5..8, INTC calc:9..12, QCOM calc:13..16.


def one(text, *ids):
    res = verify(Draft(claims=[Claim(text=text, source_ids=list(ids))]), RESULTS)
    return res


def test_planted_wrong_number_is_caught():  # AC4
    good = Claim(text="NVIDIA's FY2025 revenue was $130.50 billion.", source_ids=[NVDA_FY25_XBRL])
    bad = Claim(text="NVIDIA's FY2025 R&D expense was $14.20 billion.",
                source_ids=[NVDA_FY25_XBRL])
    res = verify(Draft(claims=[good, bad]), RESULTS)
    assert res.ok_claims == [good]
    (claim, reason), = res.failed_claims
    assert claim == bad
    assert reason.startswith(f"14200000000 not found in cited {NVDA_FY25_XBRL} (has ")
    assert "12914000000" in reason


@pytest.mark.parametrize("text", [
    "NVIDIA's FY2025 revenue was $130.50 billion.",      # billions, rounded
    "NVIDIA's FY2025 revenue was $130.497 billion.",
    "NVIDIA's FY2025 revenue was $130,497 million.",     # millions
    "NVIDIA's FY2025 revenue was 130,497,000,000 USD.",  # raw value as rendered in evidence
    "NVIDIA's FY2025 revenue was 130.5.",                # unit dropped
])
def test_correct_numbers_in_any_scale_pass(text):
    assert one(text, NVDA_FY25_XBRL).failed_claims == []


def test_slightly_off_number_fails():
    assert one("NVIDIA's FY2025 revenue was $131.5 billion.", NVDA_FY25_XBRL).failed_claims


def test_number_from_another_filing_fails():
    # FY2024 revenue is real evidence, but the claim cites only the FY2025 filing.
    assert one("NVIDIA's revenue was $60.92 billion.", NVDA_FY25_XBRL).failed_claims


def test_percentages_from_calc_results():
    # INTC rd_share_2025 = 16,900 / 50,200 * 100 = 33.665...
    assert one("Intel's R&D share of revenue was 33.67% in FY2025.", "calc:11").ok_claims
    assert one("Intel's R&D share of revenue was 33.7% in FY2025.", "calc:11").ok_claims
    assert one("Intel's R&D share of revenue was 35.1% in FY2025.", "calc:11").failed_claims


def test_percent_vs_fraction_result():
    res = verify(Draft(claims=[Claim(text="Margin was 75.0%.", source_ids=["calc:f"])]),
                 [calcs_fraction()])
    assert res.ok_claims


def calcs_fraction():
    from src.tools.types import Source, ToolResult
    return ToolResult(ok=True, data=[{"source_id": "calc:f", "ticker": "NVDA", "name": "gm",
                                      "expression": "gp / rev", "values": {}, "result": 0.7499,
                                      "input_source_ids": []}],
                      sources=[Source(source_id="calc:f", kind="calc")])


def test_calc_counts_its_input_facts():
    # calc:4 = NVDA gross_margin_2025, inputs from the FY2025 filing.
    text = ("NVIDIA's FY2025 gross margin was 74.99%, on gross profit of $97.86 billion and "
            "revenue of $130.50 billion.")
    assert one(text, "calc:4").ok_claims
    # FY2024 revenue is not an input of calc:4.
    assert one("NVIDIA's gross margin was 74.99% on revenue of $60.92 billion.",
               "calc:4").failed_claims


def test_numbers_from_chunk_text():
    assert one("NVIDIA's gross margin rose to 75.0% in FY2025 from 72.7%.",
               "chunk:7f1c2e9a").ok_claims
    assert one("Inventory provisions were $3.7 billion in FY2025.", "chunk:7f1c2e9a").ok_claims
    assert one("NVIDIA's gross margin rose to 78.0% in FY2025.", "chunk:7f1c2e9a").failed_claims


def test_any_cited_source_may_hold_the_number():
    text = "NVIDIA's gross margin was 75.0% on revenue of $130.50 billion in FY2025."
    assert one(text, "chunk:7f1c2e9a", NVDA_FY25_XBRL).ok_claims


def test_unknown_id_fails():
    (_, reason), = one("Revenue was $130.50 billion.", NVDA_FY25_XBRL, "xbrl:bogus").failed_claims
    assert reason == "cites unknown source id(s): xbrl:bogus"


def test_no_source_fails():
    (_, reason), = one("Revenue was $130.50 billion.").failed_claims
    assert reason == "cites no source"


def test_claim_without_numbers_passes_with_known_source():
    assert one("Intel was the only company whose R&D share rose while gross margin fell.",
               "calc:9", "calc:10", "calc:11", "calc:12").ok_claims


@pytest.mark.parametrize("text", [
    "Item 7 of the 10-K reports gross margin of 75.0%.",
    "Of the 4 companies, NVIDIA had a gross margin of 75.0%.",
    "Item 1A risk factors mention a gross margin of 75.0%.",
    "NVIDIA's gross margin was 75.0%, per Item 7.",
])
def test_label_integers_are_ignored(text):
    assert checked_numbers(text) == [75.0]
    assert one(text, "chunk:7f1c2e9a").ok_claims


@pytest.mark.parametrize("text,expected", [
    ("Margin was 7%.", [7.0]),
    ("It paid $7 per share.", [7.0]),
    ("Revenue was 7 billion.", [7e9]),
    ("Revenue rose 7.0 points.", [7.0]),
    ("Revenue was 130 thousand.", [130e3]),
    ("It has 120 subsidiaries.", [120.0]),           # >= 100: checked
])
def test_value_like_numbers_are_checked(text, expected):
    assert checked_numbers(text) == pytest.approx(expected)


def test_failed_tool_results_are_not_evidence():
    from src.tools.types import ToolResult
    res = verify(Draft(claims=[Claim(text="Revenue was $1 billion.", source_ids=["xbrl:a"])]),
                 [ToolResult.fail("timeout")])
    assert res.failed_claims[0][1] == "cites unknown source id(s): xbrl:a"


def test_not_found_draft_is_empty_result():
    res = verify(Draft(not_found=True), RESULTS)
    assert res.ok_claims == [] and res.failed_claims == []


def test_feedback_text_lists_claims_and_reasons():
    bad = Claim(text="Revenue was $140 billion.", source_ids=[NVDA_FY25_XBRL])
    fb = feedback_text(verify(Draft(claims=[bad]), RESULTS))
    assert fb.startswith(f'- "Revenue was $140 billion." (cited {NVDA_FY25_XBRL}): '
                         "140000000000 not found")
