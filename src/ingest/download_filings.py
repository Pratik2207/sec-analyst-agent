"""Download 10-K primary documents from EDGAR (FR-1). [track-a]

Which filings: one per (ticker, fiscal_year) already in financial_facts (Phase 1), so the
text and the numbers share the same accession_no, fiscal_year and period_end.
Primary document name: from https://data.sec.gov/submissions/CIK##########.json.
All HTTP goes through src.sec_client.SecClient (User-Agent, <=10 req/s, cache).

Output: data/raw/filings/<ticker>/<accession_no>.htm and data/raw/filings/manifest.jsonl,
one line per filing: {ticker, cik, company, sector, fiscal_year, period_end, accession_no,
source_url, path}.

Usage: uv run python -m src.ingest.download_filings [--all]
"""

import argparse
import json
import logging
import re
from pathlib import Path

from config.settings import DATA_DIR, ROOT, load_companies
from src.sec_client import SecClient

FILINGS_DIR = DATA_DIR / "raw" / "filings"
MANIFEST = FILINGS_DIR / "manifest.jsonl"
SUBMISSIONS_DIR = DATA_DIR / "raw" / "submissions"

SUBMISSIONS_URL = "https://data.sec.gov/submissions/{name}"
ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/{doc}"

FILINGS_SQL = """SELECT DISTINCT f.ticker, f.fiscal_year, f.period_end, f.accession_no,
c.cik, c.name, c.sector
FROM financial_facts f JOIN companies c ON c.ticker = f.ticker
ORDER BY f.ticker, f.fiscal_year"""

log = logging.getLogger(__name__)


# Names from SEC's submissions JSON become cache paths and URL path segments: allow only
# the shapes SEC uses, so a bad value can't escape data/raw/ or alter the URL.
SUBMISSIONS_PAGE_RE = re.compile(r"CIK\d{10}-submissions-\d{3}\.json")
DOCUMENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")


def _check_name(name: str, pattern: re.Pattern, what: str) -> str:
    if not pattern.fullmatch(name) or ".." in name:
        raise ValueError(f"unexpected {what} from SEC submissions: {name!r}")
    return name


def _find_in_page(page: dict, accession_no: str) -> str | None:
    accns = page.get("accessionNumber", [])
    if accession_no in accns:
        doc = page["primaryDocument"][accns.index(accession_no)]
        return _check_name(doc, DOCUMENT_RE, "primaryDocument")
    return None


def primary_document(client: SecClient, cik: str, accession_no: str,
                     submissions_dir: Path = SUBMISSIONS_DIR) -> str:
    """Primary document file name of a filing, from the (cached) submissions JSON.

    Heavy filers have older filings only in the extra pages listed in `filings.files`.
    """
    cik = str(cik).zfill(10)
    name = f"CIK{cik}.json"
    sub = client.get_json_cached(SUBMISSIONS_URL.format(name=name), submissions_dir / name)
    doc = _find_in_page(sub["filings"]["recent"], accession_no)
    for extra in sub["filings"].get("files", []):
        if doc is not None:
            break
        page_name = _check_name(extra["name"], SUBMISSIONS_PAGE_RE, "submissions page")
        page = client.get_json_cached(SUBMISSIONS_URL.format(name=page_name),
                                      submissions_dir / page_name)
        doc = _find_in_page(page, accession_no)
    if doc is None:
        raise LookupError(f"{accession_no} not found in submissions for CIK{cik}")
    return doc


def _display_path(path: Path) -> str:
    """Repo-relative POSIX path when inside the repo, else absolute."""
    return path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)


def download(refs: list[dict], client: SecClient, filings_dir: Path = FILINGS_DIR,
             submissions_dir: Path = SUBMISSIONS_DIR) -> list[dict]:
    """Download each filing ref ({ticker, cik, company, sector, fiscal_year, period_end,
    accession_no}) and return the manifest records. Existing files are not re-downloaded."""
    records = []
    for ref in refs:
        path = filings_dir / ref["ticker"] / f"{ref['accession_no']}.htm"
        try:
            doc = primary_document(client, ref["cik"], ref["accession_no"], submissions_dir)
        except (LookupError, ValueError) as e:
            log.warning("skipping %s %s: %s", ref["ticker"], ref["fiscal_year"], e)
            continue
        url = ARCHIVE_URL.format(cik=int(ref["cik"]),
                                 accn=ref["accession_no"].replace("-", ""), doc=doc)
        if not path.exists():
            body = client.get_bytes(url)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            log.info("downloaded %s FY%s (%d bytes)", ref["ticker"], ref["fiscal_year"],
                     len(body))
        records.append({**{k: ref[k] for k in ("ticker", "cik", "company", "sector",
                                               "fiscal_year", "period_end", "accession_no")},
                        "source_url": url, "path": _display_path(path)})
    return records


def write_manifest(records: list[dict], path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


def load_refs(all_companies: bool = False) -> list[dict]:
    """One filing ref per (ticker, fiscal_year) in financial_facts, via the read-only role."""
    from src.tools import sql_tool

    res = sql_tool.run(FILINGS_SQL, max_rows=10_000)
    if not res["ok"]:
        raise RuntimeError(f"could not read financial_facts: {res['error']}")
    tickers = {c["ticker"] for c in load_companies(pilot_only=not all_companies)}
    return [{"ticker": r["ticker"], "cik": r["cik"], "company": r["name"],
             "sector": r["sector"], "fiscal_year": r["fiscal_year"],
             "period_end": r["period_end"], "accession_no": r["accession_no"]}
            for r in res["rows"] if r["ticker"] in tickers]


def main(all_companies: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    refs = load_refs(all_companies)
    client = SecClient()
    records = download(refs, client)
    write_manifest(records)
    print(f"{len(records)}/{len(refs)} filings in {MANIFEST} "
          f"({client.network_calls} network calls)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--all", action="store_true", help="all 50 companies, not just the pilot")
    main(ap.parse_args().all)
