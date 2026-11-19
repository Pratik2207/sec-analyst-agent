from datetime import date

import pytest

from config.settings import load_metric_map
from src.ingest.download_xbrl import extract_metrics, find_annual_filings, fy_end_month


def fact(val, end, accn, fy, start=None, form="10-K", fp="FY", filed="2025-03-01"):
    f = {"val": val, "end": end, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start:
        f["start"] = start
    return f


def facts(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": v}} for t, v in tags.items()}}}


NV = "0001045810-25-000023"
NVIDIA_LIKE = facts(
    Revenues=[
        fact(130_497e6, "2025-01-26", NV, 2025, start="2024-01-29"),
        fact(60_922e6, "2024-01-28", NV, 2025, start="2023-01-30"),  # prior-year comparative
    ],
    GrossProfit=[fact(97_858e6, "2025-01-26", NV, 2025, start="2024-01-29")],
    Assets=[fact(111_601e6, "2025-01-26", NV, 2025), fact(65_728e6, "2024-01-28", NV, 2025)],
)


def test_fiscal_year_and_period_end_come_from_the_filing():
    filing = find_annual_filings(NVIDIA_LIKE)[2025]
    assert filing.period_end == date(2025, 1, 26)
    assert filing.accession_no == NV


def test_current_period_values_not_comparatives():
    rows = {r.metric: r for r in extract_metrics(NVIDIA_LIKE, "NVDA", load_metric_map())}
    assert rows["revenue"].value == 130_497e6
    assert rows["revenue"].fiscal_year == 2025
    assert rows["total_assets"].value == 111_601e6  # instant fact
    assert rows["gross_profit"].xbrl_tag == "GrossProfit"


def test_tag_fallback_maps_to_same_canonical_metric():
    mm = load_metric_map()
    a = facts(Revenues=[fact(10.0, "2024-12-31", "A-1", 2024, start="2024-01-01")])
    b = facts(RevenueFromContractWithCustomerExcludingAssessedTax=[
        fact(20.0, "2024-12-31", "B-1", 2024, start="2024-01-01")])
    ra = extract_metrics(a, "A", mm, years=(2024,))
    rb = extract_metrics(b, "B", mm, years=(2024,))
    assert [(r.metric, r.xbrl_tag) for r in ra] == [("revenue", "Revenues")]
    assert [(r.metric, r.xbrl_tag) for r in rb] == [
        ("revenue", "RevenueFromContractWithCustomerExcludingAssessedTax")]


def test_gross_profit_derived_when_not_reported():
    pharma = facts(
        Revenues=[fact(100.0, "2024-12-31", "P-1", 2024, start="2024-01-01")],
        CostOfGoodsAndServicesSold=[fact(30.0, "2024-12-31", "P-1", 2024, start="2024-01-01")],
    )
    rows = {r.metric: r for r in extract_metrics(pharma, "PFE", load_metric_map(), (2024,))}
    assert rows["gross_profit"].value == 70.0
    assert rows["gross_profit"].xbrl_tag == "derived:Revenues-CostOfGoodsAndServicesSold"


def test_quarterly_and_amended_facts_ignored():
    data = facts(Revenues=[
        fact(5.0, "2024-12-31", "Q-1", 2024, start="2024-10-01", form="10-Q", fp="Q4"),
        fact(7.0, "2024-12-31", "A-1", 2024, start="2024-01-01", form="10-K/A"),
    ])
    assert extract_metrics(data, "X", load_metric_map(), (2024,)) == []


@pytest.mark.parametrize("end,month", [
    (date(2025, 1, 26), 1), (date(2024, 12, 28), 12), (date(2025, 1, 2), 12),
    (date(2024, 9, 29), 9), (date(2024, 10, 3), 9),
])
def test_fy_end_month(end, month):
    assert fy_end_month(end) == month
