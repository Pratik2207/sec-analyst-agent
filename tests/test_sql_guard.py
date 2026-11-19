import pytest

from src.tools.sql_tool import SqlRejected, check_select, run

OK = [
    "SELECT ticker, value, accession_no FROM financial_facts WHERE metric = 'revenue'",
    "WITH x AS (SELECT * FROM companies) SELECT ticker FROM x",
    "SELECT 1 UNION SELECT 2",
]

BAD = [
    "DELETE FROM financial_facts",
    "SELECT 1; DROP TABLE companies",
    "SELECT 1; -- comment\nDELETE FROM companies",
    "/* hi */ UPDATE companies SET name = 'x'",
    "INSERT INTO companies VALUES ('X','1','x','y',1)",
    "WITH d AS (DELETE FROM companies RETURNING *) SELECT * FROM d",
    "SELECT * INTO newtable FROM companies",
    "SELECT * FROM companies FOR UPDATE",
    "CREATE TABLE t (a int)",
    "SET statement_timeout = 0",
    "COPY companies TO '/tmp/x'",
    "",
]


@pytest.mark.parametrize("sql", OK)
def test_allowed(sql):
    check_select(sql)


@pytest.mark.parametrize("sql", BAD)
def test_rejected(sql):
    with pytest.raises(SqlRejected):
        check_select(sql)


def test_run_rejects_without_touching_db():
    out = run("DELETE FROM companies", url="postgresql://nobody@127.0.0.1:1/none")
    assert out["ok"] is False and "SELECT" in out["error"]
