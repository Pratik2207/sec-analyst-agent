"""list_companies tool, with sql_tool.run stubbed (no database in unit tests)."""

from src.tools import companies_tool

ROWS = [
    {"ticker": "BAC", "name": "Bank of America", "sector": "banks", "fy_end_month": 12},
    {"ticker": "NVDA", "name": "NVIDIA", "sector": "semiconductors", "fy_end_month": 1},
    {"ticker": "PFE", "name": "Pfizer", "sector": "pharma", "fy_end_month": 12},
]


def _stub(monkeypatch, result):
    calls = []

    def fake_run(sql, params=None, **kw):
        calls.append(sql)
        return result

    monkeypatch.setattr(companies_tool.sql_tool, "run", fake_run)
    return calls


def _ok():
    return {"ok": True, "columns": list(ROWS[0]), "rows": ROWS, "truncated": False,
            "error": None}


def test_all_companies(monkeypatch):
    calls = _stub(monkeypatch, _ok())
    res = companies_tool.call()
    assert res.ok
    assert [d["ticker"] for d in res.data] == ["BAC", "NVDA", "PFE"]
    assert "SELECT ticker, name, sector, fy_end_month FROM companies" in calls[0]
    banks = res.data[0]
    assert "rd_expense" not in banks["metrics"] and "revenue" in banks["metrics"]
    assert "rd_expense" in res.data[1]["metrics"]
    assert res.data[1]["fy_end_month"] == 1


def test_sql_passes_the_guard():
    companies_tool.sql_tool.check_select(companies_tool._SQL)


def test_sector_filter(monkeypatch):
    _stub(monkeypatch, _ok())
    res = companies_tool.call(sector="Semiconductors")
    assert res.ok
    assert [d["ticker"] for d in res.data] == ["NVDA"]


def test_unknown_sector(monkeypatch):
    calls = _stub(monkeypatch, _ok())
    res = companies_tool.call(sector="airlines")
    assert not res.ok and "banks" in res.error
    assert calls == []


def test_db_error(monkeypatch):
    _stub(monkeypatch, {"ok": False, "columns": [], "rows": [], "truncated": False,
                        "error": "database error: boom"})
    res = companies_tool.call()
    assert not res.ok and "boom" in res.error


def test_source_id_invariant(monkeypatch):
    _stub(monkeypatch, _ok())
    res = companies_tool.call()
    for d in res.data:
        src = res.source(d["source_id"])
        assert src is not None and src.kind == "companies"
        assert src.citation() is None


def test_spec_sector_enum():
    props = companies_tool.SPEC["function"]["parameters"]["properties"]
    assert props["sector"]["enum"] == ["banks", "pharma", "semiconductors"]
