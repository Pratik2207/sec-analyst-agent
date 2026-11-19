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

from config.settings import DATA_DIR

FILINGS_DIR = DATA_DIR / "raw" / "filings"
MANIFEST = FILINGS_DIR / "manifest.jsonl"


def main(all_companies: bool = False) -> None:
    raise NotImplementedError("track-a")
