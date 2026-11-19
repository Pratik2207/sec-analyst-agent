"""Download XBRL companyfacts JSON and load canonical metrics into PostgreSQL (FR-2, FR-3).

Fiscal year (X-3): each 10-K's facts carry `fy` = the filing's DocumentFiscalYearFocus.
The filing's period_end is the latest end date of its full-year facts. A metric's value
for that fiscal year is the fact in that same 10-K whose period ends on period_end.

Usage: uv run python -m src.ingest.download_xbrl [--all]
"""

import argparse
from dataclasses import dataclass
from datetime import date

import psycopg

from config.settings import DATA_DIR, FISCAL_YEARS, load_companies, load_metric_map
from src.db import owner_connect
from src.sec_client import SecClient

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
ANNUAL_DAYS = range(350, 380)  # 52/53-week and calendar fiscal years


@dataclass(frozen=True)
class FactRow:
    ticker: str
    fiscal_year: int
    period_end: date
    metric: str
    value: float
    unit: str
    xbrl_tag: str
    accession_no: str


@dataclass(frozen=True)
class Filing:
    accession_no: str
    fiscal_year: int
    period_end: date
    filed: date


def _days(fact: dict) -> int | None:
    if "start" not in fact:
        return None
    return (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days


def _usd_facts(facts_json: dict, tag: str) -> list[dict]:
    return facts_json.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(
        "USD", []
    )


def find_annual_filings(facts_json: dict) -> dict[int, Filing]:
    """Map fiscal year -> the original 10-K for that year."""
    by_accn: dict[str, dict] = {}
    for tag_data in facts_json.get("facts", {}).get("us-gaap", {}).values():
        for fact in tag_data.get("units", {}).get("USD", []):
            if fact.get("form") != "10-K" or fact.get("fp") != "FY" or fact.get("fy") is None:
                continue
            days = _days(fact)
            if days is None or days not in ANNUAL_DAYS:
                continue
            info = by_accn.setdefault(
                fact["accn"], {"fy": fact["fy"], "end": fact["end"], "filed": fact["filed"]}
            )
            info["end"] = max(info["end"], fact["end"])
    filings: dict[int, Filing] = {}
    for accn, info in by_accn.items():
        f = Filing(accn, int(info["fy"]), date.fromisoformat(info["end"]),
                   date.fromisoformat(info["filed"]))
        prev = filings.get(f.fiscal_year)
        # Prefer the filing covering the latest period; among equals, the earliest filed.
        if prev is None or (f.period_end, -f.filed.toordinal()) > (
            prev.period_end, -prev.filed.toordinal()
        ):
            filings[f.fiscal_year] = f
    return filings


def _value_for(facts_json: dict, tag: str, kind: str, filing: Filing) -> float | None:
    end = filing.period_end.isoformat()
    for fact in _usd_facts(facts_json, tag):
        if fact.get("accn") != filing.accession_no or fact["end"] != end:
            continue
        days = _days(fact)
        if kind == "instant" and days is None:
            return float(fact["val"])
        if kind == "duration" and days is not None and days in ANNUAL_DAYS:
            return float(fact["val"])
    return None


def _first_tag(facts_json: dict, spec: dict, filing: Filing) -> tuple[str, float] | None:
    for tag in spec["tags"]:
        value = _value_for(facts_json, tag, spec["kind"], filing)
        if value is not None:
            return tag, value
    return None


def _derive(facts_json: dict, derive: dict, metrics: dict, helpers: dict,
            filing: Filing) -> tuple[str, float] | None:
    """value = a <op> b; an `optional` b that isn't reported counts as 0."""
    op = derive["op"]
    if op not in ("-", "+"):
        raise ValueError(f"unsupported derive op {op!r}")
    a_name, b_name = derive["args"]
    a = _first_tag(facts_json, metrics.get(a_name) or helpers[a_name], filing)
    b = _first_tag(facts_json, metrics.get(b_name) or helpers[b_name], filing)
    if b is None and b_name in derive.get("optional", []):
        b = ("none", 0.0)
    if a is None or b is None:
        return None
    value = a[1] - b[1] if op == "-" else a[1] + b[1]
    return f"derived:{a[0]}{op}{b[0]}", value


def extract_metrics(facts_json: dict, ticker: str, metric_map: dict,
                    years: tuple[int, ...] = FISCAL_YEARS) -> list[FactRow]:
    metrics, helpers = metric_map["metrics"], metric_map.get("helpers", {})
    filings = find_annual_filings(facts_json)
    rows: list[FactRow] = []
    for year in years:
        filing = filings.get(year)
        if filing is None:
            continue
        for metric, spec in metrics.items():
            found = _first_tag(facts_json, spec, filing)
            if found is None and "derive" in spec:
                found = _derive(facts_json, spec["derive"], metrics, helpers, filing)
            if found is None:
                continue
            tag, value = found
            rows.append(FactRow(ticker, year, filing.period_end, metric, value, "USD", tag,
                                filing.accession_no))
    return rows


def fy_end_month(period_end: date) -> int:
    """Month the fiscal year ends in; 52/53-week years ending in a month's first week
    (e.g. 2024-12-28 vs 2025-01-02) count as the prior month."""
    if period_end.day <= 7:
        return 12 if period_end.month == 1 else period_end.month - 1
    return period_end.month


def upsert_company(conn: psycopg.Connection, company: dict, month: int | None) -> None:
    conn.execute(
        "INSERT INTO companies (ticker, cik, name, sector, fy_end_month) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (ticker) DO UPDATE SET "
        "cik = EXCLUDED.cik, name = EXCLUDED.name, sector = EXCLUDED.sector, "
        "fy_end_month = COALESCE(EXCLUDED.fy_end_month, companies.fy_end_month)",
        (company["ticker"], company["cik"], company["name"], company["sector"], month),
    )


def upsert_facts(conn: psycopg.Connection, rows: list[FactRow]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO financial_facts (ticker, fiscal_year, period_end, metric, value, unit, "
            "xbrl_tag, accession_no) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (ticker, fiscal_year, metric) DO UPDATE SET "
            "period_end = EXCLUDED.period_end, value = EXCLUDED.value, unit = EXCLUDED.unit, "
            "xbrl_tag = EXCLUDED.xbrl_tag, accession_no = EXCLUDED.accession_no",
            [(r.ticker, r.fiscal_year, r.period_end, r.metric, r.value, r.unit, r.xbrl_tag,
              r.accession_no) for r in rows],
        )


def load_company(conn: psycopg.Connection, client: SecClient, company: dict,
                 metric_map: dict) -> int:
    cache = DATA_DIR / "raw" / "xbrl" / f"CIK{company['cik']}.json"
    facts_json = client.get_json_cached(COMPANYFACTS_URL.format(cik=company["cik"]), cache)
    rows = extract_metrics(facts_json, company["ticker"], metric_map)
    latest = max((r.period_end for r in rows), default=None)
    upsert_company(conn, company, fy_end_month(latest) if latest else None)
    upsert_facts(conn, rows)
    return len(rows)


def main(all_companies: bool = False) -> None:
    companies = load_companies(pilot_only=not all_companies)
    metric_map = load_metric_map()
    client = SecClient()
    with owner_connect() as conn:
        for company in companies:
            n = load_company(conn, client, company, metric_map)
            conn.commit()
            print(f"{company['ticker']:6} {n:3} facts")
    print(f"done: {len(companies)} companies, {client.network_calls} network calls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="all 50 companies, not just pilot")
    main(parser.parse_args().all)
