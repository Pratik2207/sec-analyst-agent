"""Split a 10-K into Items (1, 1A, 7, 7A, 8) and then by subheading (FR-4). [track-a]

Output: data/processed/sections/<accession_no>.json. If Items can't be found, the whole
document is returned under item "full" and the failure is logged (X-4).

Usage: uv run python -m src.ingest.parse_sections
"""

from config.settings import DATA_DIR

SECTIONS_DIR = DATA_DIR / "processed" / "sections"


def main() -> None:
    raise NotImplementedError("track-a")
