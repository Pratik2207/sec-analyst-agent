"""Phase 1 tester: extra integration tests (criteria 1, 2, 4, 5, 6; FR-2, FR-8, NFR-9, X-3)."""

import json
import subprocess
import sys

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import conninfo_to_dict

from config.settings import ROOT, get_settings, load_companies, load_metric_map
from src.api.main import app
from src.db import setup
from src.tools import sql_tool

pytestmark = pytest.mark.integration


# ---- criterion 1: postgres on localhost:5433/sec_analyst --------------------------------------

def test_owner_connects_to_localhost_5433_sec_analyst():
    info = conninfo_to_dict(get_settings().database_url)
    assert info.get("host") in ("localhost", "127.0.0.1") and str(info.get("port")) == "5433"
    assert info.get("dbname") == "sec_analyst"
    with psycopg.connect(get_settings().database_url, connect_timeout=3) as conn:
        assert conn.execute("SHOW server_version").fetchone()[0].startswith("16")


def test_qdrant_is_up():
    assert httpx.get("http://localhost:6333/readyz", timeout=3).status_code == 200


# ---- setup idempotency + role settings (NFR-9) -------------------------------------------------

def test_setup_is_idempotent(test_urls):
    setup(test_urls["owner"], test_urls["reader"])
    setup(test_urls["owner"], test_urls["reader"])
    with psycopg.connect(test_urls["owner"]) as conn:
        n = conn.execute("SELECT count(*) FROM metric_map").fetchone()[0]
    assert n == sum(len(s["tags"]) for s in load_metric_map()["metrics"].values())


def test_reader_session_has_5s_timeout_and_read_only(test_urls):
    with psycopg.connect(test_urls["reader"]) as conn:
        assert conn.execute("SHOW statement_timeout").fetchone()[0] == "5s"
        assert conn.execute("SHOW default_transaction_read_only").fetchone()[0] == "on"


@pytest.mark.parametrize("stmt", [
    "UPDATE metric_map SET metric = 'x'",
    "DELETE FROM metric_map",
    "CREATE TABLE evil (a int)",
    "DROP TABLE metric_map",
    "TRUNCATE metric_map",
])
def test_reader_writes_refused_by_db_even_in_read_write_txn(test_urls, stmt):
    with psycopg.connect(test_urls["reader"], autocommit=True) as conn:
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.Error):
            conn.execute(stmt)


def test_timeout_cannot_be_disabled_from_inside_a_select(test_urls):
    out = sql_tool.run("SELECT set_config('statement_timeout', '0', false), pg_sleep(6)",
                       url=test_urls["reader"])
    assert out["ok"] is False
    assert "timeout" in out["error"].lower() or "cancel" in out["error"].lower()


# ---- sql_query against loaded data (FR-8) ------------------------------------------------------

@pytest.fixture(scope="module")
def loaded_once(test_urls):
    from src.ingest.download_xbrl import load_company
    from src.sec_client import SecClient

    client = SecClient()
    with psycopg.connect(test_urls["owner"]) as conn:
        for company in load_companies(pilot_only=True):
            load_company(conn, client, company, load_metric_map())
    assert client.network_calls == 0, "pilot XBRL should come from data/raw/xbrl cache"
    return test_urls


def test_every_returned_fact_row_has_accession_no(loaded_once):
    out = sql_tool.run("SELECT ticker, fiscal_year, metric, value, accession_no "
                       "FROM financial_facts", url=loaded_once["reader"])
    assert out["ok"], out["error"]
    assert out["rows"] and all(r["accession_no"] for r in out["rows"])


def test_sql_tool_truncates(loaded_once):
    out = sql_tool.run("SELECT ticker, accession_no FROM financial_facts",
                       url=loaded_once["reader"], max_rows=5)
    assert out["ok"] and len(out["rows"]) == 5 and out["truncated"] is True


@pytest.mark.parametrize("sql", [
    "DELETE FROM financial_facts",
    "SELECT 1; DROP TABLE financial_facts",
    "SELECT 1; -- c\nDELETE FROM financial_facts",
    "/* x */ DELETE FROM financial_facts",
])
def test_sql_tool_rejections_leave_data_intact(loaded_once, sql):
    with psycopg.connect(loaded_once["owner"]) as conn:
        before = conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0]
    assert sql_tool.run(sql, url=loaded_once["reader"])["ok"] is False
    with psycopg.connect(loaded_once["owner"]) as conn:
        assert conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0] == before > 0


def test_all_six_metrics_loaded_where_sector_reports_them(loaded_once):
    sectors = load_metric_map()["sectors"]
    with psycopg.connect(loaded_once["owner"]) as conn:
        have = set(conn.execute("SELECT ticker, metric FROM financial_facts").fetchall())
    for c in load_companies(pilot_only=True):
        for metric in sectors[c["sector"]]:
            assert (c["ticker"], metric) in have, (c["ticker"], metric)


def test_fiscal_year_matches_period_end_for_non_calendar_filers(loaded_once):
    with psycopg.connect(loaded_once["owner"]) as conn:
        rows = dict(conn.execute(
            "SELECT DISTINCT ticker || ':' || fiscal_year, period_end::text FROM financial_facts "
            "WHERE ticker IN ('NVDA', 'QCOM')").fetchall())
    assert rows["NVDA:2025"] == "2025-01-26"
    assert rows["NVDA:2024"] == "2024-01-28"
    assert rows["QCOM:2024"].startswith("2024-09")


# ---- CLI commands (criteria 2 and 3) -----------------------------------------------------------

def _run(*args):
    return subprocess.run([sys.executable, "-m", *args], cwd=ROOT, capture_output=True,
                          text=True, timeout=300)


def test_coverage_cli_reports_zero_gaps_on_real_db():
    r = _run("src.ingest.coverage")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "MISSING" not in r.stdout and r.stdout.strip().splitlines()[-1].startswith("0 gaps")


def test_download_cli_rerun_keeps_row_count_and_uses_cache():
    with psycopg.connect(get_settings().database_url) as conn:
        before = conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0]
    r = _run("src.ingest.download_xbrl")
    assert r.returncode == 0, r.stderr
    assert "0 network calls" in r.stdout
    with psycopg.connect(get_settings().database_url) as conn:
        assert conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0] == before > 0


# ---- /ask end to end with Ollama (criterion 6, X-3) ------------------------------------------

@pytest.fixture(scope="module")
def client():
    try:
        httpx.get(get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")
    return TestClient(app)


def _db_fact(ticker, metric, year):
    out = sql_tool.run("SELECT value, period_end, accession_no FROM financial_facts "
                       "WHERE ticker = %s AND metric = %s AND fiscal_year = %s",
                       (ticker, metric, year))
    assert out["ok"] and out["rows"], out["error"]
    return out["rows"][0]


def test_ask_intel_rd_matches_db_accession(client):
    body = client.post("/ask", json={
        "question": "What was Intel's R&D expense in FY2024?"}).json()
    fact = _db_fact("INTC", "rd_expense", 2024)
    [c] = body["citations"]
    assert c["accession_no"] == fact["accession_no"]
    assert fact["accession_no"].replace("-", "") in c["url"]
    assert f"{fact['value'] / 1e9:,.2f}" in body["answer"]


def test_ask_states_fiscal_year_and_period_end(client):
    body = client.post("/ask", json={"question": "What was NVIDIA's revenue in fiscal 2025?"})
    answer = body.json()["answer"]
    assert "2025" in answer and "2025-01-26" in answer and "130.50 billion" in answer, answer


def test_ask_bank_gross_profit_is_not_found(client):
    body = client.post("/ask", json={
        "question": "What was JPMorgan Chase's gross profit in FY2024?"}).json()
    assert body["answer"] == "Not found in the filings." and body["citations"] == []


def test_ask_response_is_json_serialisable_with_steps(client):
    body = client.post("/ask", json={"question": "Pfizer total assets FY2023?"}).json()
    json.dumps(body)
    assert body["steps"][0]["name"] == "route"   # Phase 3: router replaced extract
