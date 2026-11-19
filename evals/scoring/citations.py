"""Citation accuracy (approximation).

PRD 10 defines it as the share of citations whose source contains the claim. Checking
"contains the claim" needs a judge per citation; this scorer approximates it: a citation is
right when its (ticker, fiscal_year) is one of the question's gold_sources. Per answer the
score is right / cited; the metric is the mean over answers that cite anything and whose
question has gold sources (unanswerable questions are skipped). It credits a citation of the
right filing even if that filing's section does not hold the claim, and misses correct
citations of a filing the gold does not list.
"""

from evals.schema import DatasetItem
from src.api.schemas import Citation


def citation_score(citations: list[Citation], item: DatasetItem) -> float | None:
    gold = {(g.ticker.upper(), g.fiscal_year) for g in item.gold_sources}
    if not citations or not gold:
        return None
    ok = sum((c.ticker.upper(), c.fiscal_year) in gold for c in citations)
    return ok / len(citations)
