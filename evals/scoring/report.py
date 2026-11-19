"""Turn cached run results, judgments and retrievals into scores, the NFR check and
report.md.

Correctness per question type:
  number        numbers.number_correct (judge only if the item has no gold_value)
  text          judge score (1 / 0.5 / 0)
  multihop      judge score; numeric match vs gold_value reported separately
  unanswerable  refusal = 1, anything else = 0
An errored run scores 0. A refusal on an answerable question scores 0 without a judge call.
A judge failure leaves the score None ("not judged"): excluded from accuracy, counted.
"""

from evals.schema import DatasetItem, RunResult
from evals.scoring.citations import citation_score
from evals.scoring.latency import percentile, summarize
from evals.scoring.numbers import number_correct
from evals.scoring.recall import first_hit_rank
from evals.scoring.refusal import is_refusal

TYPES = ("number", "text", "multihop", "unanswerable")
HEADLINE = ("agent", "baseline")


def needs_judge(item: DatasetItem, rr: RunResult) -> bool:
    """Correctness needs the LLM judge for this result."""
    if rr.error or rr.response is None or is_refusal(rr.response.answer):
        return False
    return item.type in ("text", "multihop") or (item.type == "number"
                                                 and item.gold_value is None)


def _tool_error(rr: RunResult) -> str | None:
    for st in rr.response.steps if rr.response else []:
        if st.name == "tool_call" and st.detail.get("ok") is False:
            return f"{st.detail.get('tool')}: {st.detail.get('error')}"
    return None


def score_result(item: DatasetItem, rr: RunResult, judgment: dict | None) -> dict:
    judgment = judgment or {}
    row = {"qid": item.id, "type": item.type, "system": rr.system, "error": rr.error,
           "route": rr.route, "wall_s": rr.wall_s, "answer": None, "refusal": False,
           "score": 0.0, "numeric_match": None, "citation": None, "faithfulness": None,
           "judge_reason": None, "tokens": None, "tool_error": _tool_error(rr)}
    if rr.error or rr.response is None:
        return row
    ans = rr.response.answer
    refused = is_refusal(ans)
    row.update(answer=ans, refusal=refused,
               tokens=rr.response.tokens.prompt + rr.response.tokens.completion,
               citation=citation_score(rr.response.citations, item))
    if item.gold_value is not None and item.type in ("number", "multihop"):
        row["numeric_match"] = not refused and number_correct(ans, item.gold_value, item.unit)
    if item.type == "unanswerable":
        row["score"] = 1.0 if refused else 0.0
    elif refused:
        row["score"] = 0.0
    elif item.type == "number" and item.gold_value is not None:
        row["score"] = 1.0 if row["numeric_match"] else 0.0
    else:
        c = judgment.get("correctness") or {}
        row["score"], row["judge_reason"] = c.get("score"), c.get("reason")
    f = judgment.get("faithfulness")
    if f:
        row["faithfulness"] = f.get("score")
    return row


def _mean(xs: list) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def summarize_rows(rows: list[dict]) -> dict:
    scored = [r["score"] for r in rows if r["score"] is not None]
    ok = [r for r in rows if not r["error"]]
    una = [r for r in rows if r["type"] == "unanswerable"]
    num = [r["numeric_match"] for r in rows if r["numeric_match"] is not None]
    return {"n": len(rows), "scored": len(scored), "not_judged": len(rows) - len(scored),
            "errors": len(rows) - len(ok),
            "accuracy": _mean(scored),
            "refusal_accuracy": _mean([1.0 if r["refusal"] else 0.0 for r in una]),
            "citation_accuracy": _mean([r["citation"] for r in rows]),
            "faithfulness": _mean([r["faithfulness"] for r in rows]),
            "numeric_match": _mean([1.0 if m else 0.0 for m in num]),
            **summarize([r["wall_s"] for r in ok], [r["tokens"] for r in ok
                                                     if r["tokens"] is not None])}


def aggregate(rows: list[dict]) -> dict:
    """{system: {type | "overall": summary}}"""
    out: dict = {}
    for system in dict.fromkeys(r["system"] for r in rows):
        mine = [r for r in rows if r["system"] == system]
        out[system] = {t: summarize_rows([r for r in mine if r["type"] == t])
                       for t in TYPES if any(r["type"] == t for r in mine)}
        out[system]["overall"] = summarize_rows(mine)
    return out


def recall_scores(items: list[DatasetItem], retrieved: dict) -> dict:
    """retrieved: {config: {qid: payloads} | None (not run)} -> {config: {...}}"""
    out = {}
    for config, by_qid in retrieved.items():
        if by_qid is None:
            out[config] = {"n": 0, "hits": 0, "recall": None, "ranks": {}}
            continue
        ranks = {it.id: first_hit_rank(by_qid[it.id], it) for it in items
                 if it.gold_contains and it.id in by_qid}
        hits = sum(r is not None for r in ranks.values())
        out[config] = {"n": len(ranks), "hits": hits,
                       "recall": hits / len(ranks) if ranks else None, "ranks": ranks}
    return out


# ---- NFRs ----------------------------------------------------------------------------

def _status(ok: bool | None) -> str:
    return "N/A" if ok is None else "PASS" if ok else "FAIL"


def _get(agg: dict, system: str, typ: str, key: str):
    return agg.get(system, {}).get(typ, {}).get(key)


def nfr_check(agg: dict, recall: dict, rows: list[dict]) -> list[dict]:
    acc = _get(agg, "agent", "overall", "accuracy")
    mh_a = _get(agg, "agent", "multihop", "accuracy")
    mh_b = _get(agg, "baseline", "multihop", "accuracy")
    gap = None if mh_a is None or mh_b is None else mh_a - mh_b
    nfr1 = None if acc is None or gap is None else (acc >= 0.80 and gap >= 0.25)

    faith = _get(agg, "agent", "overall", "faithfulness")
    rec = recall.get("full", {}).get("recall")
    fast = [r["wall_s"] for r in rows
            if r["system"] == "agent" and r["route"] == "fast" and not r["error"]]
    fast_p50 = percentile(fast, 50)
    mh50 = _get(agg, "agent", "multihop", "p50_s")
    mh95 = _get(agg, "agent", "multihop", "p95_s")
    nfr5 = None if mh50 is None or mh95 is None else (mh50 < 60 and mh95 < 120)
    return [
        {"id": "NFR-1", "target": "agent accuracy >= 80%; agent - baseline >= 25 pts on multihop",
         "measured": f"accuracy {pct(acc)}; multihop gap {pts(gap)}", "status": _status(nfr1)},
        {"id": "NFR-2", "target": "agent faithfulness >= 95%", "measured": pct(faith),
         "status": _status(None if faith is None else faith >= 0.95)},
        {"id": "NFR-3", "target": "recall@10 (full config) >= 85%", "measured": pct(rec),
         "status": _status(None if rec is None else rec >= 0.85)},
        {"id": "NFR-4", "target": "fast-path p50 < 5 s",
         "measured": f"{sec(fast_p50)} (n={len(fast)})",
         "status": _status(None if fast_p50 is None else fast_p50 < 5)},
        {"id": "NFR-5", "target": "agent multihop p50 < 60 s, p95 < 120 s",
         "measured": f"p50 {sec(mh50)}, p95 {sec(mh95)}", "status": _status(nfr5)},
    ]


# ---- failures ------------------------------------------------------------------------

def failure_cause(row: dict, item: DatasetItem, recall_full: dict) -> str:
    if row["error"] or row["tool_error"]:
        return "exception/tool error"
    if row["refusal"] and item.type != "unanswerable":
        return "refused but answerable"
    if item.type == "unanswerable":
        return "answered unanswerable"
    ranks = recall_full.get("ranks", {}) if recall_full else {}
    if item.id in ranks and ranks[item.id] is None:
        return "retrieval miss"
    if row["numeric_match"] is False:
        return "wrong number"
    return "judge-incorrect" if row["score"] == 0 else "judge-partial"


def failures(rows: list[dict], items: dict[str, DatasetItem], recall: dict) -> list[dict]:
    out = []
    for r in rows:
        if r["system"] != "agent" or r["score"] is None or r["score"] >= 1:
            continue
        it = items[r["qid"]]
        excerpt = (r["answer"] or r["error"] or "").replace("\n", " ")
        out.append({"qid": r["qid"], "type": r["type"], "question": it.question,
                    "answer": excerpt[:160] + ("..." if len(excerpt) > 160 else ""),
                    "cause": failure_cause(r, it, recall.get("full"))})
    return out


# ---- markdown ------------------------------------------------------------------------

def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def pts(x: float | None) -> str:
    return "n/a" if x is None else f"{100 * x:+.1f} pts"


def sec(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.1f} s"


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:,.0f}"


def _cell(s) -> str:
    return str(s).replace("|", "\\|")


def render(meta: dict, agg: dict, recall: dict, nfrs: list[dict], fails: list[dict]) -> str:
    L = [f"# Eval report: {meta['run_id']}", "",
         f"Date: {meta['date']}. Dataset: `{meta['dataset']}` ({meta['n_items']} questions: "
         + ", ".join(f"{t} {n}" for t, n in meta["counts"].items()) + ").", "",
         "## Headline: agent vs baseline", "",
         "| Type | System | N | Accuracy | Refusal acc. | Citation acc. | Faithfulness "
         "| p50 | p95 | Tokens/q |",
         "|---|---|---|---|---|---|---|---|---|---|"]
    for typ in (*TYPES, "overall"):
        for system in HEADLINE:
            s = agg.get(system, {}).get(typ)
            if not s:
                continue
            nj = f" ({s['not_judged']} not judged)" if s["not_judged"] else ""
            L.append(f"| {typ} | {system} | {s['n']} | {pct(s['accuracy'])}{nj} "
                     f"| {pct(s['refusal_accuracy'])} | {pct(s['citation_accuracy'])} "
                     f"| {pct(s['faithfulness'])} | {sec(s['p50_s'])} | {sec(s['p95_s'])} "
                     f"| {_num(s['tokens_mean'])} |")
    mh = [(sy, agg[sy]["multihop"]["numeric_match"]) for sy in HEADLINE
          if "multihop" in agg.get(sy, {}) and agg[sy]["multihop"]["numeric_match"] is not None]
    if mh:
        L += ["", "Multihop numeric match (items with a gold_value): "
              + "; ".join(f"{sy} {pct(v)}" for sy, v in mh) + "."]
    L += ["", "Refusal accuracy is measured on unanswerable questions; a refusal on an "
          "answerable question scores 0. Citation accuracy approximates \"source contains the "
          "claim\" by (ticker, fiscal_year) in the gold sources. Latency excludes errored runs.",
          "", "## Ablations", "", "### End to end", "",
          "| System | Type | N | Accuracy | p50 | p95 | Tokens/q |",
          "|---|---|---|---|---|---|---|"]
    for system in [s for s in agg if s not in HEADLINE]:
        for typ in (*TYPES, "overall"):
            s = agg[system].get(typ)
            if s:
                ref = agg.get("agent", {}).get(typ, {}).get("accuracy")
                L.append(f"| {system} | {typ} | {s['n']} | {pct(s['accuracy'])} "
                         f"(agent {pct(ref)}) | {sec(s['p50_s'])} | {sec(s['p95_s'])} "
                         f"| {_num(s['tokens_mean'])} |")
    L += ["", "### Retrieval recall@10", "", "| Config | Questions | Hits | Recall@10 |",
          "|---|---|---|---|"]
    for config, r in recall.items():
        L.append(f"| {config} | {r['n'] or 'n/a'} | {r['hits'] if r['n'] else 'n/a'} "
                 f"| {pct(r['recall'])} |")
    L += ["", "## NFR check", "", "| NFR | Target | Measured | Status |", "|---|---|---|---|"]
    L += [f"| {n['id']} | {n['target']} | {n['measured']} | **{n['status']}** |" for n in nfrs]
    L += ["", f"## Agent failures ({len(fails)})", ""]
    if fails:
        counts: dict[str, int] = {}
        for f in fails:
            counts[f["cause"]] = counts.get(f["cause"], 0) + 1
        L += ["By cause: " + ", ".join(f"{c} {n}" for c, n in
                                       sorted(counts.items(), key=lambda kv: -kv[1])) + ".", "",
              "| QID | Type | Cause | Question | Answer excerpt |", "|---|---|---|---|---|"]
        L += [f"| {f['qid']} | {f['type']} | {f['cause']} | {_cell(f['question'])} "
              f"| {_cell(f['answer'])} |" for f in fails]
    else:
        L.append("None.")
    L += ["", "## Run metadata", ""]
    L += [f"- {k}: {v}" for k, v in meta.items()]
    return "\n".join(L) + "\n"
