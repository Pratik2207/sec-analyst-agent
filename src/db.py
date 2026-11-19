"""Database setup: schema, metric_map table, and the read-only agent_reader role.

Usage: uv run python -m src.db setup
"""

import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from config.settings import ROOT, get_settings, load_metric_map

SCHEMA_SQL = ROOT / "sql" / "schema.sql"
STATEMENT_TIMEOUT = "5s"


def owner_connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or get_settings().database_url)


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_SQL.read_text(encoding="utf-8"))


def load_metric_map_table(conn: psycopg.Connection) -> int:
    """Upsert every tag in config/metric_map.yaml (metrics only, not helpers)."""
    rows = []
    seen: dict[str, str] = {}
    for metric, spec in load_metric_map()["metrics"].items():
        for tag in spec["tags"]:
            if tag in seen:
                raise ValueError(f"tag {tag} mapped to both {seen[tag]} and {metric}")
            seen[tag] = metric
            rows.append((tag, metric))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO metric_map (xbrl_tag, metric) VALUES (%s, %s) "
            "ON CONFLICT (xbrl_tag) DO UPDATE SET metric = EXCLUDED.metric",
            rows,
        )
    return len(rows)


def ensure_reader_role(conn: psycopg.Connection, reader_url: str | None = None) -> None:
    """Create/refresh the SELECT-only role named in AGENT_DATABASE_URL."""
    info = conninfo_to_dict(reader_url or get_settings().agent_database_url)
    role, password = info["user"], info.get("password")
    if not password:
        raise ValueError("AGENT_DATABASE_URL must include a password")
    dbname = conn.info.dbname
    exists = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
    verb = "ALTER" if exists else "CREATE"
    ident = sql.Identifier(role)
    conn.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(ident, sql.Literal(password)))
    for stmt in (
        "GRANT CONNECT ON DATABASE {db} TO {r}",
        "GRANT USAGE ON SCHEMA public TO {r}",
        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO {r}",
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO {r}",
        "ALTER ROLE {r} SET default_transaction_read_only = on",
    ):
        conn.execute(sql.SQL(stmt).format(db=sql.Identifier(dbname), r=ident))
    conn.execute(
        sql.SQL("ALTER ROLE {} SET statement_timeout = {}").format(
            ident, sql.Literal(STATEMENT_TIMEOUT)
        )
    )


def setup(owner_url: str | None = None, reader_url: str | None = None) -> None:
    with owner_connect(owner_url) as conn:
        apply_schema(conn)
        n = load_metric_map_table(conn)
        ensure_reader_role(conn, reader_url)
    print(f"schema applied, {n} metric_map tags loaded, read-only role ready")


if __name__ == "__main__":
    if sys.argv[1:] != ["setup"]:
        sys.exit("usage: python -m src.db setup")
    setup()
