import psycopg
import pytest

from config.settings import load_companies, load_metric_map
from src.ingest.coverage import find_gaps
from src.ingest.download_xbrl import load_company
from src.sec_client import SecClient
from src.tools import sql_tool

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def loaded(test_urls):
    """Pilot companies loaded twice into the test DB (from the local cache if present)."""
    client = SecClient()
    counts = []
    for _ in range(2):
        with psycopg.connect(test_urls["owner"]) as conn:
            for company in load_companies(pilot_only=True):
                load_company(conn, client, company, load_metric_map())
            counts.append(conn.execute("SELECT count(*) FROM financial_facts").fetchone()[0])
    return counts


def test_reload_is_idempotent(loaded):
    assert loaded[0] == loaded[1] > 0


def test_pilot_coverage_has_no_gaps(loaded, test_urls):
    with psycopg.connect(test_urls["owner"]) as conn:
        assert find_gaps(conn, load_companies(pilot_only=True)) == []


def test_nvidia_fy2025_period_end(loaded, test_urls):
    out = sql_tool.run(
        "SELECT period_end, value, accession_no FROM financial_facts "
        "WHERE ticker = 'NVDA' AND fiscal_year = 2025 AND metric = 'revenue'",
        url=test_urls["reader"])
    assert out["ok"], out["error"]
    assert out["rows"][0]["period_end"] == "2025-01-26"


def test_reader_cannot_write(test_urls):
    with psycopg.connect(test_urls["reader"]) as conn, pytest.raises(psycopg.Error):
        conn.execute("INSERT INTO metric_map VALUES ('X', 'y')")


def test_reader_cannot_write_even_after_disabling_read_only(test_urls):
    with psycopg.connect(test_urls["reader"]) as conn, pytest.raises(psycopg.Error):
        conn.execute("SET default_transaction_read_only = off")
        conn.execute("BEGIN READ WRITE")
        conn.execute("INSERT INTO metric_map VALUES ('X', 'y')")


def test_reader_statement_timeout(test_urls):
    out = sql_tool.run("SELECT pg_sleep(6)", url=test_urls["reader"])
    assert out["ok"] is False
    assert "timeout" in out["error"].lower() or "cancel" in out["error"].lower()


def test_sql_tool_requires_accession_for_facts(loaded, test_urls):
    out = sql_tool.run("SELECT ticker, value FROM financial_facts LIMIT 1",
                       url=test_urls["reader"])
    assert out["ok"] is False and "accession_no" in out["error"]
