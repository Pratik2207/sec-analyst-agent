"""Phase 5 tester: the real dataset re-checked independently against
evals/data/facts_pilot.json, plus validator edge cases."""

import json
import re
from collections import Counter
from pathlib import Path

import pytest

from evals.schema import DATASET, EXPECTED_COUNTS, load_dataset
from evals.validate_dataset import FACTS, validate

ITEMS = load_dataset()
BY_ID = {it.id: it for it in ITEMS}
FACT_ROWS = json.loads(Path(FACTS).read_text(encoding="utf-8"))
F = {(r["ticker"], r["fiscal_year"], r["metric"]): r for r in FACT_ROWS}


def v(t, y, m):
    return F[(t, y, m)]["value"]


# ---- the real dataset ------------------------------------------------------------------

def test_counts_ids_and_gold_presence():
    assert Counter(it.type for it in ITEMS) == Counter(EXPECTED_COUNTS)
    assert len({it.id for it in ITEMS}) == 120
    for it in ITEMS:
        assert it.gold_answer.strip(), it.id
        if it.type != "unanswerable":
            assert it.gold_sources, it.id


NAMES = {"NVDA": ("nvidia",), "AMD": ("amd", "advanced micro"), "INTC": ("intel",),
         "QCOM": ("qualcomm", "qcom"), "JPM": ("jpmorgan",), "BAC": ("bank of america", "bofa"),
         "GS": ("goldman",), "PFE": ("pfizer",), "LLY": ("lilly",), "MRK": ("merck",)}
METRIC_WORDS = {"rd_expense": ("r&d", "research and development"),
                "net_income": ("net income",), "operating_income": ("operating income",),
                "total_assets": ("total assets",), "gross_profit": ("gross profit",),
                "revenue": ("revenue", "sales")}


@pytest.mark.parametrize("it", [i for i in ITEMS if i.type == "number"], ids=lambda i: i.id)
def test_number_gold_matches_fact_and_question(it):
    """gold_value == the XBRL fact, and the question names that company, year and metric."""
    metric = re.search(r"metric=(\w+)", it.notes).group(1)
    s = it.gold_sources[0]
    fact = F[(s.ticker, s.fiscal_year, metric)]
    assert it.gold_value == fact["value"]
    assert s.accession_no == fact["accession_no"]
    q = it.question.lower()
    assert any(n in q for n in NAMES[s.ticker]), "company not in question"
    yy = str(s.fiscal_year)
    assert yy in q or re.search(rf"fy\s?{yy[2:]}\b", q), "year not in question"
    assert any(w in q for w in METRIC_WORDS[metric]), "metric not in question"
    assert it.unit == "USD"


# Independent recomputation of every multihop gold from the facts.
SEMIS, BANKS, PHARMA = ("AMD", "INTC", "NVDA", "QCOM"), ("BAC", "GS", "JPM"), ("LLY", "MRK", "PFE")


def ratio(t, y, num, den):
    return 100 * v(t, y, num) / v(t, y, den)


def growth(t, m, y0, y1):
    return 100 * (v(t, y1, m) - v(t, y0, m)) / abs(v(t, y0, m))


def pp(t, num, den, y0, y1):
    return ratio(t, y1, num, den) - ratio(t, y0, num, den)


MULTIHOP = {
    "mh-001": lambda: max(v(t, 2025, "net_income") for t in BANKS),
    "mh-002": lambda: growth("LLY", "revenue", 2023, 2025),
    "mh-004": lambda: max(ratio(t, 2024, "rd_expense", "revenue") for t in PHARMA),
    "mh-005": lambda: pp("AMD", "gross_profit", "revenue", 2023, 2024),
    "mh-006": lambda: growth("NVDA", "revenue", 2024, 2025),
    "mh-007": lambda: v("INTC", 2023, "net_income") - v("INTC", 2024, "net_income"),
    "mh-008": lambda: max(ratio(t, 2025, "operating_income", "revenue") for t in SEMIS),
    "mh-009": lambda: v("JPM", 2024, "total_assets") - v("BAC", 2024, "total_assets"),
    "mh-010": lambda: growth("GS", "net_income", 2023, 2025),
    "mh-011": lambda: max(ratio(t, 2024, "net_income", "revenue") for t in BANKS),
    "mh-012": lambda: pp("QCOM", "rd_expense", "revenue", 2023, 2025),
    "mh-013": lambda: v("MRK", 2024, "net_income") - v("MRK", 2023, "net_income"),
    "mh-014": lambda: sum(v(t, 2025, "revenue") for t in BANKS),
    "mh-015": lambda: max(v(t, 2025, "revenue") for t in PHARMA),
    "mh-017": lambda: growth("AMD", "rd_expense", 2023, 2025),
    "mh-018": lambda: pp("INTC", "gross_profit", "revenue", 2023, 2025),
    "mh-019": lambda: max(v(t, 2025, "rd_expense") for t in SEMIS),
    "mh-020": lambda: pp("NVDA", "net_income", "revenue", 2024, 2025),
    "mh-021": lambda: growth("PFE", "revenue", 2023, 2024),
    "mh-022": lambda: max(ratio(t, 2025, "net_income", "total_assets") for t in ("BAC", "JPM")),
    "mh-023": lambda: growth("QCOM", "net_income", 2024, 2025),
    "mh-024": lambda: (ratio("LLY", 2025, "gross_profit", "revenue")
                       - ratio("MRK", 2025, "gross_profit", "revenue")),
    "mh-025": lambda: sum(v(t, 2023, "rd_expense") for t in PHARMA),
    "mh-026": lambda: max(v(t, 2025, "total_assets") for t in SEMIS),
    "mh-027": lambda: growth("GS", "revenue", 2024, 2025),
    "mh-028": lambda: growth("AMD", "operating_income", 2024, 2025),
    "mh-029": lambda: v("NVDA", 2025, "revenue") - v("INTC", 2025, "revenue"),
    "mh-030": lambda: pp("MRK", "rd_expense", "revenue", 2023, 2024),
}
RANKINGS = {   # rank questions have no gold_value: check the order in gold_answer
    "mh-003": sorted(SEMIS, key=lambda t: -ratio(t, 2024, "gross_profit", "revenue")),
    "mh-016": sorted(PHARMA, key=lambda t: -v(t, 2025, "net_income")),
}


def test_every_multihop_item_is_covered():
    assert set(MULTIHOP) | set(RANKINGS) == {it.id for it in ITEMS if it.type == "multihop"}


@pytest.mark.parametrize("qid", sorted(MULTIHOP))
def test_multihop_gold_recomputed(qid):
    it = BY_ID[qid]
    got = MULTIHOP[qid]()
    if it.unit in ("%", "pp"):
        assert abs(got - it.gold_value) <= 0.0051, (got, it.gold_value)   # 2-dp rounding
    else:
        assert it.unit == "USD"
        assert got == pytest.approx(it.gold_value, rel=1e-9), (got, it.gold_value)


@pytest.mark.parametrize("qid", sorted(RANKINGS))
def test_multihop_ranking_order_in_gold_answer(qid):
    ans = BY_ID[qid].gold_answer
    pos = [ans.index(t) for t in RANKINGS[qid]]
    assert pos == sorted(pos), (RANKINGS[qid], ans)


def test_unanswerables_have_no_matching_fact():
    """Spot checks: the 'not in the data' questions really are not in the facts."""
    assert ("PFE", 2030, "revenue") not in F
    assert ("AMD", 2019, "net_income") not in F
    assert ("BAC", 2024, "rd_expense") not in F
    assert ("GS", 2025, "rd_expense") not in F
    assert not {t for t, _, _ in F} & {"AAPL", "TSLA", "MSFT"}


# ---- validator edge cases --------------------------------------------------------------

def _num(**kw):
    d = {"id": "num-001", "type": "number", "question": "What was AMD's revenue in 2023?",
         "gold_answer": "$22.68 billion", "gold_value": 22680000000.0, "unit": "USD",
         "gold_sources": [{"ticker": "AMD", "fiscal_year": 2023, "item": "8"}]}
    return {**d, **kw}


def _run(tmp_path, lines, counts=None):
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(x if isinstance(x, str) else json.dumps(x) for x in lines),
                 encoding="utf-8")
    return validate(p, FACTS, None, counts)[0]


def test_blank_lines_ignored_and_bad_json_reported(tmp_path):
    probs = _run(tmp_path, [_num(), "", "   ", "{not json"])
    assert len(probs) == 1 and probs[0].startswith("line 4")


def test_bad_type_is_a_schema_problem(tmp_path):
    assert any("invalid item" in p for p in _run(tmp_path, [_num(type="ratio")]))


def test_value_off_by_1000_dollars_is_rejected(tmp_path):
    assert any("!= fact" in p for p in _run(tmp_path, [_num(gold_value=22680001000.0)]))
    assert _run(tmp_path, [_num(gold_value=22680000000.4)]) == []   # within abs_tol 0.5


def test_metric_inference_net_loss_and_sales(tmp_path):
    q1 = _num(question="What was Intel's net loss in FY2024?", gold_value=-18756000000.0,
              gold_sources=[{"ticker": "INTC", "fiscal_year": 2024}])
    q2 = _num(id="num-002", question="What were Merck's total sales in FY23?",
              gold_value=60115000000.0, gold_sources=[{"ticker": "MRK", "fiscal_year": 2023}])
    assert _run(tmp_path, [q1, q2]) == []


def test_gross_profit_not_inferred_as_revenue(tmp_path):
    q = _num(question="What was AMD's gross profit on revenue in 2024?", gold_value=12725e6,
             gold_sources=[{"ticker": "AMD", "fiscal_year": 2024}])
    assert _run(tmp_path, [q]) == []


def test_id_prefix_must_match_type(tmp_path):
    assert any("does not match type" in p for p in _run(tmp_path, [_num(id="txt-001")]))
    assert any("does not match type" in p for p in _run(tmp_path, [_num(id="num-1")]))


def test_duplicate_question_ignores_case_and_spaces(tmp_path):
    q2 = _num(id="num-002", question="  what was AMD's   REVENUE in 2023? ")
    assert any("duplicate question" in p for p in _run(tmp_path, [_num(), q2]))


def test_whitespace_gold_answer_and_empty_question(tmp_path):
    probs = _run(tmp_path, [_num(gold_answer="  "), _num(id="num-002", question=" ")])
    assert any("empty gold_answer" in p for p in probs)
    assert any("empty question" in p for p in probs)


def test_counts_skipped_when_none_and_reported_otherwise(tmp_path):
    assert _run(tmp_path, [_num()], counts=None) == []
    probs = _run(tmp_path, [_num()], counts=EXPECTED_COUNTS)
    assert sum(p.startswith("count:") for p in probs) == 4


def test_real_dataset_validates_clean():
    problems, _ = validate(DATASET)
    assert problems == []
