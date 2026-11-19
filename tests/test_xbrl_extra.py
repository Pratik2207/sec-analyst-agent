"""Phase 1 tester: extra unit tests for XBRL extraction, metric map, coverage (FR-2/3, X-1/2/3)."""

from datetime import date

from config.settings import FISCAL_YEARS, load_metric_map
from src.ingest.coverage import find_gaps
from src.ingest.download_xbrl import extract_metrics, find_annual_filings
from tests.test_xbrl import fact, facts

MM = load_metric_map()
CANONICAL = {"revenue", "gross_profit", "rd_expense", "operating_income", "net_income",
             "total_assets"}


def test_metric_map_defines_all_canonical_metrics():
    assert set(MM["metrics"]) == CANONICAL


def test_no_tag_maps_to_two_metrics():
    tags = [t for spec in MM["metrics"].values() for t in spec["tags"]]
    assert len(tags) == len(set(tags))


def test_both_revenue_tags_listed_under_revenue():
    tags = MM["metrics"]["revenue"]["tags"]
    assert "Revenues" in tags
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in tags


def test_fallback_order_first_tag_wins_when_both_reported():
    data = facts(
        Revenues=[fact(10.0, "2024-12-31", "A-1", 2024, start="2024-01-01")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            fact(20.0, "2024-12-31", "A-1", 2024, start="2024-01-01")],
    )
    [row] = extract_metrics(data, "A", MM, (2024,))
    assert (row.xbrl_tag, row.value) == ("Revenues", 10.0)


def test_second_tag_used_when_first_missing_for_that_filing():
    data = facts(
        Revenues=[fact(10.0, "2023-12-31", "A-0", 2023, start="2023-01-01")],
        RevenueFromContractWithCustomerExcludingAssessedTax=[
            fact(20.0, "2024-12-31", "A-1", 2024, start="2024-01-01")],
    )
    rows = {r.fiscal_year: r for r in extract_metrics(data, "A", MM, (2023, 2024))}
    assert rows[2024].xbrl_tag == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert rows[2023].xbrl_tag == "Revenues"


def test_all_six_metrics_extracted_with_accession_and_unit():
    accn, end, start = "S-1", "2024-12-28", "2023-12-31"
    data = facts(
        Revenues=[fact(100.0, end, accn, 2024, start=start)],
        GrossProfit=[fact(60.0, end, accn, 2024, start=start)],
        ResearchAndDevelopmentExpense=[fact(20.0, end, accn, 2024, start=start)],
        OperatingIncomeLoss=[fact(30.0, end, accn, 2024, start=start)],
        NetIncomeLoss=[fact(25.0, end, accn, 2024, start=start)],
        Assets=[fact(500.0, end, accn, 2024)],
    )
    rows = extract_metrics(data, "SEMI", MM, (2024,))
    assert {r.metric for r in rows} == CANONICAL
    assert all(r.accession_no == accn and r.unit == "USD" and r.period_end == date(2024, 12, 28)
               for r in rows)


def test_fiscal_year_comes_from_fy_not_calendar_year_of_period_end():
    data = facts(Revenues=[
        fact(2.0, "2025-01-26", "N-25", 2025, start="2024-01-29"),
        fact(1.0, "2024-01-28", "N-24", 2024, start="2023-01-30"),
    ])
    filings = find_annual_filings(data)
    assert filings[2025].period_end == date(2025, 1, 26)
    assert filings[2024].period_end == date(2024, 1, 28)
    rows = {r.fiscal_year: r.value for r in extract_metrics(data, "N", MM, (2024, 2025))}
    assert rows == {2024: 1.0, 2025: 2.0}


def test_values_from_other_filings_are_not_used():
    # FY2024 revenue appears only as a comparative in the FY2025 10-K; the FY2024 filing has none.
    data = facts(
        Revenues=[fact(2.0, "2025-12-31", "B", 2025, start="2025-01-01"),
                  fact(1.0, "2024-12-31", "B", 2025, start="2024-01-01")],
        NetIncomeLoss=[fact(3.0, "2024-12-31", "A", 2024, start="2024-01-01")],
    )
    rows = extract_metrics(data, "X", MM, (2024,))
    assert [(r.metric, r.accession_no) for r in rows] == [("net_income", "A")]


def test_non_annual_duration_in_10k_ignored():
    data = facts(Revenues=[fact(5.0, "2024-12-31", "A", 2024, start="2024-07-01")])
    assert extract_metrics(data, "X", MM, (2024,)) == []


def test_later_period_filing_preferred_for_same_fy():
    data = facts(Revenues=[
        fact(1.0, "2023-12-31", "OLD", 2024, start="2023-01-01", filed="2024-02-01"),
        fact(2.0, "2024-12-31", "NEW", 2024, start="2024-01-01", filed="2025-02-01"),
    ])
    assert find_annual_filings(data)[2024].accession_no == "NEW"


def test_derivation_skipped_when_cost_missing():
    data = facts(Revenues=[fact(100.0, "2024-12-31", "P", 2024, start="2024-01-01")])
    assert {r.metric for r in extract_metrics(data, "P", MM, (2024,))} == {"revenue"}


def test_empty_companyfacts_gives_no_rows():
    assert extract_metrics({}, "X", MM) == []
    assert extract_metrics({"facts": {}}, "X", MM) == []


# ---- X-2 sector lists + X-1 coverage --------------------------------------------------------

def test_sector_lists_are_subsets_of_canonical_and_banks_exempt():
    for metrics in MM["sectors"].values():
        assert set(metrics) <= CANONICAL
    assert "gross_profit" not in MM["sectors"]["banks"]
    assert "rd_expense" not in MM["sectors"]["banks"]
    for sector in ("semiconductors", "pharma"):
        assert {"revenue", "gross_profit", "rd_expense"} <= set(MM["sectors"][sector])


class FakeConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, *_):
        return self

    def fetchall(self):
        return self.rows


def test_find_gaps_uses_sector_lists():
    companies = [{"ticker": "JPM", "sector": "banks"},
                 {"ticker": "NVDA", "sector": "semiconductors"}]
    have = [("JPM", y, m) for y in FISCAL_YEARS for m in MM["sectors"]["banks"]]
    have += [("NVDA", y, m) for y in FISCAL_YEARS for m in MM["sectors"]["semiconductors"]]
    assert find_gaps(FakeConn(have), companies) == []
    missing = [r for r in have if r != ("NVDA", 2024, "rd_expense")]
    assert find_gaps(FakeConn(missing), companies) == [("NVDA", 2024, "rd_expense")]


def test_find_gaps_reports_everything_for_empty_db():
    gaps = find_gaps(FakeConn([]), [{"ticker": "PFE", "sector": "pharma"}])
    assert len(gaps) == len(FISCAL_YEARS) * len(MM["sectors"]["pharma"])
