"""Reader-role hardening and metric_map sync (post Phase 1 review)."""

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from src.db import ensure_reader_role, load_metric_map_table

pytestmark = pytest.mark.integration


def test_refuses_owner_as_reader(test_urls):
    owner_as_reader = test_urls["owner"]
    with psycopg.connect(test_urls["owner"]) as conn, pytest.raises(ValueError, match="different"):
        ensure_reader_role(conn, owner_as_reader)


def test_refuses_privileged_role(test_urls):
    with psycopg.connect(test_urls["owner"], autocommit=True) as conn:
        conn.execute("DROP ROLE IF EXISTS tmp_priv_reader")
        conn.execute("CREATE ROLE tmp_priv_reader LOGIN CREATEDB PASSWORD 'x-test-only'")
        try:
            url = make_conninfo(test_urls["reader"], user="tmp_priv_reader", password="x")
            with pytest.raises(ValueError, match="elevated"):
                ensure_reader_role(conn, url)
        finally:
            conn.execute("DROP ROLE tmp_priv_reader")


def test_reader_role_still_set_up(test_urls):
    user = conninfo_to_dict(test_urls["reader"])["user"]
    with psycopg.connect(test_urls["owner"]) as conn:
        row = conn.execute("SELECT rolsuper, rolcreaterole FROM pg_roles WHERE rolname = %s",
                           (user,)).fetchone()
    assert row == (False, False)


def test_metric_map_table_drops_stale_tags(test_urls):
    with psycopg.connect(test_urls["owner"]) as conn:
        conn.execute("INSERT INTO metric_map VALUES ('StaleTag', 'revenue') "
                     "ON CONFLICT DO NOTHING")
        n = load_metric_map_table(conn)
        tags = {r[0] for r in conn.execute("SELECT xbrl_tag FROM metric_map")}
    assert "StaleTag" not in tags and len(tags) == n
    assert "ResearchAndDevelopmentExpenseExcludingAcquiredInProcessCost" not in tags
