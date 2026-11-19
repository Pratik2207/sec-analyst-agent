import json

import httpx
import pytest

from src.ingest import download_filings as dl
from src.sec_client import SecClient

CIK = "0000012345"
ACCN = "0000012345-25-000010"
OLD_ACCN = "0000012345-23-000007"
DOC_URL = "https://www.sec.gov/Archives/edgar/data/12345/000001234525000010/acme-20241231.htm"
OLD_DOC_URL = "https://www.sec.gov/Archives/edgar/data/12345/000001234523000007/acme-2022.htm"

SUBMISSIONS = {
    "cik": "12345",
    "filings": {
        "recent": {"accessionNumber": ["0000012345-25-000099", ACCN],
                   "primaryDocument": ["8k.htm", "acme-20241231.htm"]},
        "files": [{"name": "CIK0000012345-submissions-001.json"}],
    },
}
OLDER_PAGE = {"accessionNumber": [OLD_ACCN], "primaryDocument": ["acme-2022.htm"]}


def ref(accn=ACCN, fy=2024):
    return {"ticker": "ACME", "cik": CIK, "company": "Acme", "sector": "industrials",
            "fiscal_year": fy, "period_end": f"{fy}-12-31", "accession_no": accn}


@pytest.fixture
def fake_sec():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if url == f"https://data.sec.gov/submissions/CIK{CIK}.json":
            return httpx.Response(200, json=SUBMISSIONS)
        if url == "https://data.sec.gov/submissions/CIK0000012345-submissions-001.json":
            return httpx.Response(200, json=OLDER_PAGE)
        if url in (DOC_URL, OLD_DOC_URL):
            return httpx.Response(200, content=b"<html>10-K " + url.encode() + b"</html>")
        return httpx.Response(404)

    def make_client():
        return SecClient("test test@example.com", 1000, transport=httpx.MockTransport(handler))

    return make_client, calls


def test_download_saves_document_and_manifest_record(tmp_path, fake_sec):
    make_client, calls = fake_sec
    records = dl.download([ref()], make_client(), tmp_path / "filings", tmp_path / "subs")
    path = tmp_path / "filings" / "ACME" / f"{ACCN}.htm"
    assert path.read_bytes().startswith(b"<html>10-K")
    assert calls == [f"https://data.sec.gov/submissions/CIK{CIK}.json", DOC_URL]
    assert (tmp_path / "subs" / f"CIK{CIK}.json").exists()
    (rec,) = records
    assert rec == {"ticker": "ACME", "cik": CIK, "company": "Acme", "sector": "industrials",
                   "fiscal_year": 2024, "period_end": "2024-12-31", "accession_no": ACCN,
                   "source_url": DOC_URL, "path": str(path)}


def test_rerun_makes_zero_network_calls(tmp_path, fake_sec):
    make_client, _ = fake_sec
    refs = [ref(), ref(OLD_ACCN, 2022)]
    first = dl.download(refs, make_client(), tmp_path / "filings", tmp_path / "subs")
    client = make_client()
    second = dl.download(refs, client, tmp_path / "filings", tmp_path / "subs")
    assert client.network_calls == 0
    assert second == first


def test_older_filing_found_in_extra_submissions_page(tmp_path, fake_sec):
    make_client, calls = fake_sec
    (rec,) = dl.download([ref(OLD_ACCN, 2022)], make_client(), tmp_path / "filings",
                         tmp_path / "subs")
    assert rec["source_url"] == OLD_DOC_URL
    assert "https://data.sec.gov/submissions/CIK0000012345-submissions-001.json" in calls
    assert (tmp_path / "subs" / "CIK0000012345-submissions-001.json").exists()
    assert (tmp_path / "filings" / "ACME" / f"{OLD_ACCN}.htm").exists()


def test_extra_pages_not_fetched_when_filing_is_recent(tmp_path, fake_sec):
    make_client, calls = fake_sec
    dl.download([ref()], make_client(), tmp_path / "filings", tmp_path / "subs")
    assert not any("submissions-001" in c for c in calls)


def test_unknown_accession_is_skipped_with_warning(tmp_path, fake_sec, caplog):
    make_client, _ = fake_sec
    records = dl.download([ref("0000012345-19-000001", 2019), ref()], make_client(),
                          tmp_path / "filings", tmp_path / "subs")
    assert [r["accession_no"] for r in records] == [ACCN]
    assert "0000012345-19-000001" in caplog.text


def test_unpadded_cik_is_padded(tmp_path, fake_sec):
    make_client, calls = fake_sec
    r = {**ref(), "cik": "12345"}
    dl.download([r], make_client(), tmp_path / "filings", tmp_path / "subs")
    assert calls[0] == f"https://data.sec.gov/submissions/CIK{CIK}.json"


def test_manifest_is_jsonl(tmp_path):
    recs = [{"ticker": "A", "accession_no": "1"}, {"ticker": "B", "accession_no": "2"}]
    path = tmp_path / "m" / "manifest.jsonl"
    dl.write_manifest(recs, path)
    assert [json.loads(line) for line in path.read_text().splitlines()] == recs


def test_load_refs_uses_read_only_sql_and_filters_pilot(monkeypatch):
    from src.tools import sql_tool

    seen = {}

    def fake_run(sql, params=None, max_rows=200, url=None):
        seen["sql"] = sql
        rows = [{"ticker": "NVDA", "fiscal_year": 2025, "period_end": "2025-01-26",
                 "accession_no": "0001045810-25-000023", "cik": "0001045810",
                 "name": "NVIDIA", "sector": "semiconductors"},
                {"ticker": "AVGO", "fiscal_year": 2024, "period_end": "2024-11-03",
                 "accession_no": "0001730168-24-000139", "cik": "0001730168",
                 "name": "Broadcom", "sector": "semiconductors"}]
        return {"ok": True, "columns": list(rows[0]), "rows": rows, "truncated": False,
                "error": None}

    monkeypatch.setattr(sql_tool, "run", fake_run)
    pilot = dl.load_refs(all_companies=False)
    assert [r["ticker"] for r in pilot] == ["NVDA"]   # AVGO is not a pilot company
    assert pilot[0]["company"] == "NVIDIA"
    assert set(pilot[0]) == {"ticker", "cik", "company", "sector", "fiscal_year",
                             "period_end", "accession_no"}
    assert [r["ticker"] for r in dl.load_refs(all_companies=True)] == ["NVDA", "AVGO"]
    assert "financial_facts" in seen["sql"] and "companies" in seen["sql"]
    sql_tool.check_select(seen["sql"])   # passes the read-only guard


def test_load_refs_raises_on_db_error(monkeypatch):
    from src.tools import sql_tool

    monkeypatch.setattr(sql_tool, "run", lambda *a, **k: {"ok": False, "error": "boom"})
    with pytest.raises(RuntimeError, match="boom"):
        dl.load_refs()
