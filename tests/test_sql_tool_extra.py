"""Phase 1 tester: extra unit tests for the sql_query guard and tool description (FR-8, X-2)."""

import pytest

from config.settings import load_metric_map
from src.tools.sql_tool import DESCRIPTION, SqlRejected, check_select, run

MORE_BAD = [
    "UPDATE financial_facts SET value = 0",
    "DROP TABLE financial_facts",
    "SELECT 1; SELECT 2",
    "SELECT 1 /* x */; /* y */ DELETE FROM companies",
    "DELETE /* SELECT */ FROM companies",
    "-- SELECT\nDELETE FROM companies",
    "SELECT $$x$$; DELETE FROM companies",
    "SELECT 'a\\'; DELETE FROM companies; --'",
    "EXPLAIN ANALYZE DELETE FROM companies",
    "DO $$BEGIN DELETE FROM companies; END$$",
    "TRUNCATE companies",
    "GRANT ALL ON companies TO PUBLIC",
    "ALTER ROLE agent_reader SET statement_timeout = 0",
    "BEGIN; DELETE FROM companies; COMMIT",
    "SELECT * FROM companies FOR SHARE",
    "   ",
    "SELEC 1",
]


@pytest.mark.parametrize("sql", MORE_BAD)
def test_more_rejected(sql):
    with pytest.raises(SqlRejected):
        check_select(sql)


@pytest.mark.parametrize("sql", [
    "SELECT 1 /* ; DROP TABLE companies */",
    "SELECT 'DELETE FROM companies; DROP TABLE x' AS s",
    "SELECT 1;",
    "select ticker from companies where name ilike '%intel%'",
])
def test_comment_or_string_content_alone_is_fine(sql):
    check_select(sql)


def test_run_never_connects_for_rejected_sql():
    out = run("SELECT 1; DROP TABLE companies", url="postgresql://nobody@127.0.0.1:1/none")
    assert out == {"ok": False, "columns": [], "rows": [], "truncated": False,
                   "error": "exactly one statement is allowed"}


def test_run_reports_db_errors_without_raising():
    out = run("SELECT 1", url="postgresql://nobody@127.0.0.1:1/none?connect_timeout=2")
    assert out["ok"] is False and out["error"].startswith("database error")


def test_description_lists_every_metric_from_config():
    for metric in load_metric_map()["metrics"]:
        assert metric in DESCRIPTION


def test_description_states_sector_exemptions_from_config():
    """X-2: the agent's tool description must reflect the per-sector metric lists in config."""
    mm = load_metric_map()
    all_metrics = set(mm["metrics"])
    for sector, expected in mm["sectors"].items():
        missing = all_metrics - set(expected)
        if missing:
            line = next((ln for ln in DESCRIPTION.splitlines()
                         if sector.lower() in ln.lower()), "")
            assert line and all(m in line for m in missing), (sector, sorted(missing))
