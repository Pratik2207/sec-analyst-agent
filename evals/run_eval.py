"""Phase 5 eval runner (FR-17). [track-b]

Usage: uv run python -m evals.run_eval [--run-id ID] [--dataset PATH] [--systems ...]
       [--limit N] [--types ...] [--skip-judge] [--skip-noheader] [--report-only]
       [--retry-errors]
Runs SYSTEMS + END_TO_END_ABLATIONS (evals.systems) on the dataset, caching every RunResult
under evals/results/<run_id>/raw/<system>/<qid>.json (resumable), scores them
(evals/scoring), runs the RETRIEVAL_ABLATIONS recall@10, and writes
evals/results/<run_id>/report.md (+ scores.json).

Phases are ordered to keep Ollama model swaps low on a one-model GPU:
  1. systems     every system on its questions (qwen3:1.7b / qwen3:4b-instruct, fastembed)
  2. judge       correctness + faithfulness with the judge model (qwen3:8b)
  3. retrieval   recall@10 per retrieval ablation (no LLM)
  4. report
Cache layout under evals/results/<run_id>/raw/:
  <system>/<qid>.json         RunResult (errored ones re-run only with --retry-errors)
  judge/<system>/<qid>.json   {"answer_sha", "correctness"?, "faithfulness"?}; only successful
                              judgments are stored, and a changed answer invalidates them
  retrieval/<config>/<qid>.json  the top-10 payloads
"""

import argparse
import hashlib
import json
import sys
import time
from datetime import date
from pathlib import Path

from evals import systems as sysmod
from evals.schema import DATASET, DatasetItem, RunResult, load_dataset
from evals.scoring import judge as judge_mod
from evals.scoring import report
from evals.scoring.faithfulness import faithfulness
from evals.scoring.refusal import is_refusal

RESULTS_DIR = Path(__file__).resolve().parent / "results"
FAITHFULNESS_SYSTEMS = ("agent", "baseline")   # headline only: saves ~70 slow judge calls


def log(msg: str) -> None:
    print(msg, flush=True)


def _hms(s: float) -> str:
    s = int(s)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


class Progress:
    """Progress lines with elapsed time and an ETA from the mean time of real (non-cached)
    work so far."""

    def __init__(self, phase: str, total: int):
        self.phase, self.total, self.done, self.worked = phase, total, 0, 0
        self.t0 = time.perf_counter()

    def step(self, label: str, cached: bool = False) -> None:
        self.done += 1
        if cached:
            return
        self.worked += 1
        el = time.perf_counter() - self.t0
        eta = el / self.worked * (self.total - self.done)
        log(f"[{self.phase} {self.done}/{self.total}] {label}  elapsed {_hms(el)}  "
            f"ETA {_hms(eta)}")


def _read(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)   # atomic: an interrupted run never leaves a half-written cache file


def _fname(system: str) -> str:
    return system.replace(":", "_")   # "agent:no_sql" is not a valid Windows directory name


def system_spec(name: str) -> tuple:
    """(callable, settings overrides, question types or None for all)"""
    if name in sysmod.SYSTEMS:
        return sysmod.SYSTEMS[name], {}, None
    base, overrides, types = sysmod.END_TO_END_ABLATIONS[name]
    return sysmod.SYSTEMS[base], overrides, types


def system_items(name: str, items: list[DatasetItem]) -> list[DatasetItem]:
    types = system_spec(name)[2]
    return [it for it in items if types is None or it.type in types]


def result_path(raw: Path, system: str, qid: str) -> Path:
    return raw / _fname(system) / f"{qid}.json"


def load_result(raw: Path, system: str, qid: str) -> RunResult | None:
    d = _read(result_path(raw, system, qid))
    return RunResult.model_validate(d) if d else None


# ---- phase 1: systems -------------------------------------------------------------------

def run_systems(items: list[DatasetItem], names: list[str], raw: Path,
                retry_errors: bool) -> dict:
    todo = {n: system_items(n, items) for n in names}
    prog = Progress("systems", sum(len(v) for v in todo.values()))
    hits = 0
    for name, its in todo.items():
        fn, overrides, _ = system_spec(name)
        with sysmod.settings_override(**overrides):
            for it in its:
                old = load_result(raw, name, it.id)
                # an edited question (user review) invalidates its cached run
                fresh = old is not None and old.extra.get("question_sha") == _sha(it.question)
                if fresh and not (retry_errors and old.error):
                    hits += 1
                    prog.step("", cached=True)
                    continue
                rr = fn(it.question)
                rr.qid, rr.system = it.id, name
                rr.extra["question_sha"] = _sha(it.question)
                _write(result_path(raw, name, it.id), rr.model_dump(mode="json"))
                prog.step(f"{name} {it.id} {rr.wall_s:.1f}s"
                          + (f" ERROR {rr.error[:80]}" if rr.error else ""))
    return {"systems_cache_hits": hits, "systems_ran": prog.worked}


# ---- phase 2: judge ---------------------------------------------------------------------

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def judge_path(raw: Path, system: str, qid: str) -> Path:
    return raw / "judge" / _fname(system) / f"{qid}.json"


def _judge_key(item: DatasetItem, rr: RunResult) -> str:
    """A judgment is valid for this question, gold answer and system answer only (the user
    may edit questions or golds after review)."""
    return _sha("|".join([item.question, item.gold_answer, rr.response.answer]))


def load_judgment(raw: Path, rr: RunResult, item: DatasetItem) -> dict:
    """Cached judgments for this exact question/gold/answer ({} when none or stale)."""
    d = _read(judge_path(raw, rr.system, rr.qid))
    if not d or rr.response is None or d.get("answer_sha") != _judge_key(item, rr):
        return {}
    return d


def judge_tasks(item: DatasetItem, rr: RunResult) -> list[str]:
    tasks = []
    if report.needs_judge(item, rr):
        tasks.append("correctness")
    if (rr.system in FAITHFULNESS_SYSTEMS and rr.response is not None and not rr.error
            and not is_refusal(rr.response.answer)):
        tasks.append("faithfulness")
    return tasks


def run_judge(items: list[DatasetItem], names: list[str], raw: Path) -> dict:
    work = []
    for name in names:
        for it in system_items(name, items):
            rr = load_result(raw, name, it.id)
            tasks = judge_tasks(it, rr) if rr else []
            if tasks:   # number/unanswerable/refused/errored results need no judge
                have = load_judgment(raw, rr, it)
                work.append((it, rr, have, [t for t in tasks if t not in have]))
    prog = Progress("judge", len(work))
    stats = {"judge_cache_hits": 0, "judge_calls": 0, "judge_failed": 0}
    for it, rr, have, missing in work:
        if not missing:
            stats["judge_cache_hits"] += 1
            prog.step("", cached=True)
            continue
        rec = {**have, "answer_sha": _judge_key(it, rr)}
        for task in missing:
            if task == "correctness":
                out = judge_mod.judge(it.question, it.gold_answer, rr.response.answer)
            else:
                out = faithfulness(rr.response.answer, rr.contexts)
            stats["judge_calls"] += 1
            if out is None or out.get("score") is None:   # not judged: retry on a re-run
                stats["judge_failed"] += 1
                continue
            rec[task] = out
        _write(judge_path(raw, rr.system, rr.qid), rec)
        prog.step(f"{rr.system} {it.id} {'+'.join(missing)}")
    return stats


# ---- phase 3: retrieval -----------------------------------------------------------------

def retrieval_path(raw: Path, config: str, qid: str) -> Path:
    return raw / "retrieval" / config / f"{qid}.json"


def run_retrieval(items: list[DatasetItem], raw: Path, skip_noheader: bool) -> dict:
    its = [it for it in items if it.gold_contains]
    configs = [c for c in sysmod.RETRIEVAL_ABLATIONS
               if not (skip_noheader and c == "no_headers")]
    if "no_headers" in configs and its:
        log("[retrieval] ensuring the no-headers collection (slow the first time)")
        log(f"[retrieval] {sysmod.ensure_noheader_collection()} points in no-headers collection")
    prog = Progress("retrieval", len(its) * len(configs))
    hits = errors = 0
    for config in configs:
        for it in its:
            path = retrieval_path(raw, config, it.id)
            if path.exists():
                hits += 1
                prog.step("", cached=True)
                continue
            try:
                payloads = sysmod.retrieve(it.question, config)
            except Exception as e:   # Qdrant/model failure: report it, retry on a re-run
                errors += 1
                log(f"[retrieval] {config} {it.id} ERROR {type(e).__name__}: {e}"[:300])
                prog.step("", cached=True)
                continue
            _write(path, {"qid": it.id, "config": config, "payloads": payloads})
            prog.step(f"{config} {it.id}")
    return {"retrieval_cache_hits": hits, "retrieval_errors": errors}


def load_retrieval(items: list[DatasetItem], raw: Path, skip_noheader: bool) -> dict:
    out = {}
    for config in sysmod.RETRIEVAL_ABLATIONS:
        found = {}
        for it in items:
            d = _read(retrieval_path(raw, config, it.id))
            if d:
                found[it.id] = d["payloads"]
        skipped = skip_noheader and config == "no_headers"
        out[config] = None if skipped and not found else found
    return out


# ---- phase 4: report --------------------------------------------------------------------

def _metadata(run_id: str, dataset: Path, items: list[DatasetItem], names: list[str],
              stats: dict) -> dict:
    from config.settings import get_settings
    s = get_settings()
    counts = {t: sum(it.type == t for it in items) for t in report.TYPES}
    return {"run_id": run_id, "date": date.today().isoformat(), "dataset": str(dataset),
            "n_items": len(items), "counts": counts, "systems": ", ".join(names),
            "models": (f"fast={s.fast_model}, planner={s.planner_model} "
                       f"(think={s.planner_think}), grader={s.grader_model}, "
                       f"answer={s.answer_model}, judge={judge_mod.JUDGE_MODEL}, "
                       f"embed={s.embed_model}, sparse={s.sparse_model}, "
                       f"rerank={s.rerank_model}"),
            "settings": (f"baseline_k={s.baseline_k}, llm_num_ctx={s.llm_num_ctx}, "
                         f"llm_timeout_s={s.llm_timeout_s}, "
                         f"collection={s.qdrant_collection}"),
            "ablations": {k: v[1:] for k, v in sysmod.END_TO_END_ABLATIONS.items()
                          if k in names},
            "faithfulness_systems": ", ".join(FAITHFULNESS_SYSTEMS),
            **stats}


def build_report(run_id: str, dataset: Path, items: list[DatasetItem], names: list[str],
                 out: Path, skip_noheader: bool, stats: dict) -> dict:
    raw = out / "raw"
    by_id = {it.id: it for it in items}
    rows, missing = [], 0
    for name in names:
        for it in system_items(name, items):
            rr = load_result(raw, name, it.id)
            if rr is None:
                missing += 1
                continue
            rows.append(report.score_result(it, rr, load_judgment(raw, rr, it)))
    agg = report.aggregate(rows)
    recall = report.recall_scores(items, load_retrieval(items, raw, skip_noheader))
    nfrs = report.nfr_check(agg, recall, rows)
    fails = report.failures(rows, by_id, recall)
    meta = _metadata(run_id, dataset, items, names, {**stats, "missing_results": missing})
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(report.render(meta, agg, recall, nfrs, fails),
                                   encoding="utf-8")
    scores = {"meta": meta, "summary": agg, "recall": recall, "nfr": nfrs,
              "failures": fails, "rows": rows}
    _write(out / "scores.json", scores)
    return scores


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    all_systems = [*sysmod.SYSTEMS, *sysmod.END_TO_END_ABLATIONS]
    p = argparse.ArgumentParser(prog="evals.run_eval", description=__doc__.split("\n")[0])
    p.add_argument("--run-id", default=date.today().isoformat())
    p.add_argument("--dataset", type=Path, default=DATASET)
    p.add_argument("--systems", nargs="+", choices=all_systems, default=all_systems)
    p.add_argument("--limit", type=int, help="only the first N questions (after --types)")
    p.add_argument("--per-type", metavar="SPEC",
                   help="stratified subset, e.g. number=10,text=10,multihop=8,unanswerable=4: "
                        "evenly spaced picks within each type (spreads companies/years); "
                        f"'quick' = {QUICK}")
    p.add_argument("--types", nargs="+", choices=report.TYPES)
    p.add_argument("--skip-judge", action="store_true", help="no judge calls (cached used)")
    p.add_argument("--skip-noheader", action="store_true",
                   help="do not build/query the no-headers collection (reported n/a)")
    p.add_argument("--report-only", action="store_true", help="rebuild the report from caches")
    p.add_argument("--retry-errors", action="store_true", help="re-run errored results")
    return p.parse_args(argv)


QUICK = "number=10,text=10,multihop=8,unanswerable=4"


def parse_per_type(spec: str) -> dict[str, int]:
    spec = QUICK if spec == "quick" else spec
    out = {}
    for part in spec.split(","):
        t, _, n = part.partition("=")
        if t.strip() not in report.TYPES or not n.strip().isdigit():
            raise SystemExit(f"bad --per-type part {part!r} (types: {', '.join(report.TYPES)})")
        out[t.strip()] = int(n)
    return out


def stratified(items: list[DatasetItem], counts: dict[str, int]) -> list[DatasetItem]:
    """Evenly spaced picks within each type (deterministic), so a subset still spans the
    companies and years the dataset is ordered by. Types not named are dropped."""
    out = []
    for t in report.TYPES:
        pool = [it for it in items if it.type == t]
        n = min(counts.get(t, 0), len(pool))
        if n:
            out += [pool[round(i * (len(pool) - 1) / max(n - 1, 1))] for i in range(n)]
    return out


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    items = load_dataset(a.dataset)
    if a.types:
        items = [it for it in items if it.type in a.types]
    if a.limit:
        items = items[:a.limit]
    if a.per_type:
        items = stratified(items, parse_per_type(a.per_type))
    out = RESULTS_DIR / a.run_id
    raw = out / "raw"
    t0 = time.perf_counter()
    stats: dict = {}
    if not a.report_only:
        stats.update(run_systems(items, a.systems, raw, a.retry_errors))
        if not a.skip_judge:
            stats.update(run_judge(items, a.systems, raw))
        stats.update(run_retrieval(items, raw, a.skip_noheader))
    scores = build_report(a.run_id, a.dataset, items, a.systems, out, a.skip_noheader, stats)
    log(f"done in {_hms(time.perf_counter() - t0)}: {out / 'report.md'}")
    for n in scores["nfr"]:
        log(f"  {n['id']} {n['status']}: {n['measured']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
