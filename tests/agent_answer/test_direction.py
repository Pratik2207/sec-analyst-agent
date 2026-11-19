"""Direction labels and the verifier's direction check (Phase 4 integration finding: the
answer model said "NVDA raised R&D share" when the change calc was negative)."""

from src.agent.evidence import direction, evidence_items, is_change
from src.agent.state import Claim, Draft
from src.agent.verifier import verify
from src.tools.types import Source, ToolResult

CALCS = ToolResult(ok=True, data=[
    {"source_id": "calc:1", "ticker": "NVDA", "name": "rd_share_change", "result": -0.043,
     "expression": "rd_expense_2025/revenue_2025 - rd_expense_2024/revenue_2024",
     "values": {}, "input_source_ids": ["xbrl:A"]},
    {"source_id": "calc:2", "ticker": "NVDA", "name": "gross_margin_change", "result": 0.023,
     "expression": "gross_profit_2025/revenue_2025 - gross_profit_2024/revenue_2024",
     "values": {}, "input_source_ids": ["xbrl:A"]},
    {"source_id": "calc:3", "ticker": "QCOM", "name": "gross_margin_change", "result": -0.008,
     "expression": "gross_profit_2025/revenue_2025 - gross_profit_2024/revenue_2024",
     "values": {}, "input_source_ids": ["xbrl:A"]},
    {"source_id": "calc:4", "ticker": "NVDA", "name": "rd_share_2025", "result": 0.099,
     "expression": "rd_expense_2025/revenue_2025", "values": {}, "input_source_ids": ["xbrl:A"]},
], sources=[Source(source_id=f"calc:{i}", kind="calc") for i in range(1, 5)])
# the facts the calcs were computed from (FR-11: claims must resolve to a filing citation)
FACTS = ToolResult(ok=True, data=[
    {"source_id": "xbrl:A", "ticker": "NVDA", "fiscal_year": 2025, "metric": "revenue",
     "value": 1.0, "accession_no": "A"}],
    sources=[Source(source_id="xbrl:A", kind="xbrl", ticker="NVDA", form="10-K",
                    fiscal_year=2025, section="Item 8", url="https://www.sec.gov/a",
                    accession_no="A")])


def _ok(text, ids=("calc:1", "calc:2", "calc:3")):
    res = verify(Draft(claims=[Claim(text=text, source_ids=list(ids))]), [CALCS, FACTS])
    return not res.failed_claims, res.failed_claims


def test_is_change_and_direction():
    assert is_change("rd_share_change", "a_2025 - a_2024")
    assert is_change("x", "rd_expense_2025/revenue_2025 - rd_expense_2024/revenue_2024")
    assert not is_change("rd_share_2025", "rd_expense_2025/revenue_2025")
    assert (direction(-1), direction(2), direction(0)) == ("decreased", "increased", "unchanged")


def test_evidence_states_direction_for_change_calcs_only():
    texts = [i.text for i in evidence_items([CALCS])]
    assert "rd_share_change = -0.043, decreased" in texts[0]
    assert "gross_margin_change = 0.023, increased" in texts[1]
    assert "increased" not in texts[3] and "decreased" not in texts[3]


def test_wrong_direction_is_rejected():
    ok, failed = _ok("NVDA raised R&D as a share of revenue, but gross margin fell.")
    assert not ok and "rd_share_change" in failed[0][1] and "decreased" in failed[0][1]


def test_wrong_direction_by_company_name():
    assert not _ok("NVIDIA's gross margin fell from FY2024 to FY2025.")[0]


def test_right_direction_passes():
    assert _ok("NVDA's R&D share of revenue decreased while its gross margin increased.")[0]
    assert _ok("QCOM's gross margin fell.")[0]


def test_no_company_or_no_direction_word_is_not_checked():
    assert _ok("None of the semiconductor companies raised R&D share while margin fell.")[0]
    assert _ok("NVDA reported its gross margin for FY2025.")[0]


def test_direction_is_scoped_to_the_clause_company():
    # live answer that was wrongly rejected: "fell" is about QCOM only, not NVDA
    text = ("All companies decreased R&D as a share of revenue: NVDA by 0.043 points. "
            "Gross margin fell only for QCOM, which decreased by 0.008 points.")
    assert _ok(text)[0]
    assert not _ok("Gross margin fell for NVDA and QCOM.")[0]   # NVDA's increased


def test_only_change_calcs_constrain_direction():
    # QCOM has no R&D change calc, and level calcs (rd_share_2025) carry no direction
    assert _ok("QCOM's R&D share was higher.", ids=("calc:3",))[0]


def test_uncited_change_calc_still_constrains():
    # the model often cites the facts rather than the calc; the check uses the company's calcs
    assert not _ok("NVDA's R&D share was higher.", ids=("calc:4",))[0]


def test_more_direction_words():
    assert not _ok("NVDA's R&D as a share of revenue climbed.")[0]
    assert not _ok("NVIDIA's gross margin dipped in FY2025.")[0]
