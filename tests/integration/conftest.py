"""Integration fixtures: a throwaway `<db>_test` database on the docker Postgres."""

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from config.settings import get_settings
from src.db import setup


def _with_db(url: str, dbname: str) -> str:
    return make_conninfo(**{**conninfo_to_dict(url), "dbname": dbname})


@pytest.fixture(scope="session")
def test_urls():
    s = get_settings()
    base = conninfo_to_dict(s.database_url)["dbname"]
    test_db = f"{base}_test"
    try:
        admin = psycopg.connect(s.database_url, autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as e:
        pytest.skip(f"postgres not reachable: {e}")
    with admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
            sql.Identifier(test_db)))
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
    owner = _with_db(s.database_url, test_db)
    reader = _with_db(s.agent_database_url, test_db)
    setup(owner, reader)
    return {"owner": owner, "reader": reader}
