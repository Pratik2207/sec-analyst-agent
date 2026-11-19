"""rd_expense has one definition: total R&D including acquired IPR&D."""

import pytest

from config.settings import load_metric_map
from src.ingest.download_xbrl import extract_metrics

EXCL = "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost"
IPRD = "ResearchAndDevelopmentAssetAcquiredOtherThanThroughBusinessCombinationWrittenOff"


def dur(val, accn="A-1"):
    return {"val": val, "start": "2024-01-01", "end": "2024-12-31", "accn": accn, "fy": 2024,
            "fp": "FY", "form": "10-K", "filed": "2025-02-01"}


def facts(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": [v]}} for t, v in tags.items()}}}


def rd(data):
    rows = [r for r in extract_metrics(data, "X", load_metric_map(), (2024,))
            if r.metric == "rd_expense"]
    return (rows[0].value, rows[0].xbrl_tag) if rows else None


def test_total_tag_used_when_reported():
    assert rd(facts(ResearchAndDevelopmentExpense=dur(30.0), **{IPRD: dur(5.0)})) == (
        30.0, "ResearchAndDevelopmentExpense")


def test_excluding_tag_gets_iprd_added_back():
    value, tag = rd(facts(**{EXCL: dur(9.31), IPRD: dur(3.80)}))
    assert value == pytest.approx(13.11)
    assert tag == f"derived:{EXCL}+{IPRD}"


def test_excluding_tag_without_iprd_counts_iprd_as_zero():
    assert rd(facts(**{EXCL: dur(10.0)})) == (10.0, f"derived:{EXCL}+none")


def test_iprd_alone_is_not_rd():
    assert rd(facts(**{IPRD: dur(3.0)})) is None


def test_bad_derive_op_rejected():
    mm = load_metric_map()
    mm["metrics"]["rd_expense"]["derive"] = {"op": "*", "args": ["rd_excluding_ipr_d",
                                                                 "acquired_ipr_d"]}
    with pytest.raises(ValueError):
        extract_metrics(facts(**{EXCL: dur(1.0)}), "X", mm, (2024,))
