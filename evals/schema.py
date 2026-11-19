"""Phase 5 interface contract: the eval dataset format and run results. Owned by main.

evals/dataset.jsonl holds one DatasetItem per line (EXPECTED_COUNTS per type).
"""

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.api.schemas import AskResponse

QuestionType = Literal["number", "text", "multihop", "unanswerable"]
EXPECTED_COUNTS = {"number": 40, "text": 40, "multihop": 30, "unanswerable": 10}
DATASET = Path(__file__).resolve().parent / "dataset.jsonl"


class GoldSource(BaseModel):
    """Where the answer is. For number questions: the 10-K whose XBRL facts hold it. For
    text questions: the section; recall@10 also uses DatasetItem.gold_contains."""
    ticker: str
    fiscal_year: int
    item: str | None = None          # "1", "1A", "7", "7A", "8" (XBRL) or "full"
    section: str | None = None
    accession_no: str | None = None


class DatasetItem(BaseModel):
    id: str                           # e.g. "num-001", "txt-014", "mh-003", "na-007"
    type: QuestionType
    question: str
    gold_answer: str                  # what a correct answer says (judge reference)
    gold_value: float | None = None   # the key number (USD, %, or pp) if there is one
    unit: str | None = None           # "USD" | "%" | "pp" | "count" | None
    gold_sources: list[GoldSource] = []
    # phrases that appear in the gold chunk(s); a retrieved chunk matching a gold source's
    # ticker/fiscal_year/item and containing ALL of them counts for recall@10
    gold_contains: list[str] = []
    author: str = "claude"            # "claude" | "user" (PRD 12: someone else writes ~20)
    notes: str = ""


class RunResult(BaseModel):
    """One system's run on one question (cached by the runner)."""
    qid: str
    system: str                       # "agent" | "baseline" | "agent:no_sql" | ...
    response: AskResponse | None = None
    contexts: list[str] = []          # the evidence the answer was written from
    route: str | None = None          # "fast" | "agent" (agent system only)
    error: str | None = None
    wall_s: float = 0.0
    extra: dict = Field(default_factory=dict)


def load_dataset(path: Path = DATASET) -> list[DatasetItem]:
    with open(path, encoding="utf-8") as f:
        return [DatasetItem.model_validate(json.loads(line)) for line in f if line.strip()]
