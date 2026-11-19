"""Coverage check (X-1): report every company x fiscal year x expected metric with no fact.

Expected metrics come from the sector lists in config/metric_map.yaml (X-2).
Exit code 1 when there are gaps.

Usage: uv run python -m src.ingest.coverage [--all]
"""

import argparse
import sys

import psycopg

from config.settings import FISCAL_YEARS, load_companies, load_metric_map
from src.db import owner_connect


def find_gaps(conn: psycopg.Connection, companies: list[dict],
              years: tuple[int, ...] = FISCAL_YEARS) -> list[tuple[str, int, str]]:
    sectors = load_metric_map()["sectors"]
    have = set(conn.execute(
        "SELECT ticker, fiscal_year, metric FROM financial_facts WHERE ticker = ANY(%s)",
        ([c["ticker"] for c in companies],),
    ).fetchall())
    return [
        (c["ticker"], year, metric)
        for c in companies
        for year in years
        for metric in sectors[c["sector"]]
        if (c["ticker"], year, metric) not in have
    ]


def main(all_companies: bool = False) -> int:
    companies = load_companies(pilot_only=not all_companies)
    with owner_connect() as conn:
        gaps = find_gaps(conn, companies)
    for ticker, year, metric in gaps:
        print(f"MISSING {ticker:6} FY{year} {metric}")
    print(f"{len(gaps)} gaps across {len(companies)} companies x {len(FISCAL_YEARS)} years")
    return 1 if gaps else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="all 50 companies, not just pilot")
    sys.exit(main(parser.parse_args().all))
