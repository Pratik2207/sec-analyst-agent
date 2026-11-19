"""The LangGraph agent loop (PRD 6.2, FR-7/10/12/14, NFR-7). [track-a]

run_agent(question: str) -> AskResponse

Nodes: plan -> execute (dispatch the step's tool) -> grade -> (retry with the rewritten
step | next step | answer) -> verify -> (re-answer once with feedback | finish).
Owns the tool dispatcher: PlanStep -> tool call. sql_query steps become a code-built
SELECT over financial_facts (+ companies for sector), always selecting accession_no;
calculate steps run the expression once per ticker with variables <metric>_<year> taken
from earlier sql_query rows, and each calc data item gets "ticker", "name" and
"input_source_ids". Bad arguments from the LLM (TypeError, wrong types, float years) must
become a failed ToolResult, never an exception. Enforce MAX_TOOL_CALLS, MAX_RETRIES and
repeated-call detection; on a stop, answer from the evidence so far (partial) and flag it.
If there is no usable evidence at all, the answer is fast_path.NOT_FOUND.
Uses answerer.answer, verifier.verify and evidence.render_answer (track-b / contract).
"""

import re
import time
from functools import lru_cache

from langgraph.graph import END, StateGraph

from src.agent import answerer, evidence, grader, planner, verifier
from src.agent.fast_path import NOT_FOUND
from src.agent.llm import LLMError
from src.agent.state import (
    MAX_ANSWER_RETRIES,
    MAX_RETRIES,
    MAX_TOOL_CALLS,
    AgentState,
    Draft,
    PlanStep,
)
from src.api.schemas import AskResponse, Step, Tokens
from src.tools import calculator, companies_tool, search_tool, section_tool, sql_tool
from src.tools.types import ToolResult

_TICKER = re.compile(r"^[A-Z.]{1,6}$")
_IDENT = re.compile(r"^[a-z_]{1,40}$")

FLAG_CAP = "partial: tool-call cap reached"
FLAG_REPEAT = "partial: repeated identical tool call"


# ---- dispatcher ------------------------------------------------------------------------

def _year(y) -> int:
    if type(y) is not int or not planner.MIN_YEAR <= y <= planner.MAX_YEAR:
        raise ValueError(f"bad fiscal year {y!r}")
    return y


def build_sql(step: PlanStep) -> str:
    """The SELECT for a sql_query step, from enum-checked values only (never question
    text). Raises ValueError on any value outside the closed sets."""
    tickers = list(step.tickers)
    for t in tickers:
        if not (isinstance(t, str) and _TICKER.match(t) and t in planner.TICKERS):
            raise ValueError(f"bad ticker {t!r}")
    if step.sector is not None and not (isinstance(step.sector, str)
                                        and _IDENT.match(step.sector)
                                        and step.sector in planner.SECTORS):
        raise ValueError(f"bad sector {step.sector!r}")
    metrics = list(step.metrics)
    if not metrics:
        raise ValueError("no metrics")
    for m in metrics:
        if not (isinstance(m, str) and _IDENT.match(m) and m in planner.METRICS):
            raise ValueError(f"bad metric {m!r}")
    if not tickers and step.sector is None:
        raise ValueError("need tickers or a sector")
    years = [_year(y) for y in step.fiscal_years]

    def in_list(col: str, vals: list) -> str:   # every value is checked above
        return f"{col} IN ({', '.join(str(v) if type(v) is int else repr(v) for v in vals)})"

    sql = ("SELECT f.ticker, f.fiscal_year, f.period_end, f.metric, f.value, f.accession_no "
           "FROM financial_facts f")
    where = []
    if step.sector is not None:
        sql += " JOIN companies c ON c.ticker = f.ticker"
        where.append(f"c.sector = '{step.sector}'")
    if tickers:
        where.append(in_list("f.ticker", tickers))
    where.append(in_list("f.metric", metrics))
    if years:
        where.append(in_list("f.fiscal_year", years))
    return f"{sql} WHERE {' AND '.join(where)} ORDER BY f.ticker, f.metric, f.fiscal_year"


def _facts_by_ticker(prior: list[ToolResult]) -> dict[str, dict[str, tuple[float, str]]]:
    """ticker -> {"<metric>_<year>": (value, source_id)} from earlier sql_query rows."""
    out: dict[str, dict[str, tuple[float, str]]] = {}
    for res in prior:
        if not res.ok:
            continue
        for d in res.data:
            if not {"ticker", "metric", "fiscal_year", "value"} <= d.keys():
                continue
            var = f"{d['metric']}_{d['fiscal_year']}"
            out.setdefault(d["ticker"], {}).setdefault(var, (d["value"], d.get("source_id")))
    return out


def run_calculate(step: PlanStep, prior: list[ToolResult]) -> tuple[ToolResult, list[str]]:
    """Evaluate step.expression once per ticker found in earlier sql rows. One merged
    ToolResult; notes list the tickers that were skipped and why."""
    if not isinstance(step.expression, str):
        raise ValueError("expression must be a string")
    names = planner.expression_names(step.expression)
    if not names:
        return ToolResult.fail("calculate: the expression has no <metric>_<year> "
                               "variables or does not parse"), []
    data, sources, notes = [], [], []
    for ticker, facts in _facts_by_ticker(prior).items():
        if step.tickers and ticker not in step.tickers:
            continue
        missing = sorted(n for n in names if n not in facts)
        if missing:
            notes.append(f"{ticker}: missing {', '.join(missing)}")
            continue
        res = calculator.call(step.expression, {n: facts[n][0] for n in names})
        if not res.ok:
            notes.append(f"{ticker}: {res.error}")
            continue
        inputs = sorted({facts[n][1] for n in names
                         if isinstance(facts[n][1], str) and facts[n][1].startswith("xbrl:")})
        data += [{**d, "ticker": ticker, "name": step.name or "result",
                  "input_source_ids": inputs} for d in res.data]
        sources += res.sources
    if not data:
        return ToolResult.fail("calculate: no company had all inputs"
                               + (f" ({'; '.join(notes)})" if notes else "")), notes
    return ToolResult(ok=True, data=data, sources=sources), notes


def dispatch(step: PlanStep, prior: list[ToolResult]) -> tuple[ToolResult, dict]:
    """Run one step's tool. Never raises: bad arguments become a failed ToolResult.
    Returns the result and extra trace detail (the SQL, calculate notes)."""
    extra: dict = {}
    try:
        if step.tool == "sql_query":
            extra["sql"] = build_sql(step)
            return sql_tool.call(extra["sql"]), extra
        if step.tool == "search_filings":
            years = [_year(y) for y in step.fiscal_years]
            return search_tool.call(
                query=step.query, ticker=step.tickers[0] if step.tickers else None,
                sector=step.sector, fiscal_year=years[0] if years else None,
                item=step.item), extra
        if step.tool == "get_section":
            if not (step.tickers and step.fiscal_years and step.item):
                raise ValueError("get_section needs a ticker, a fiscal year and an item")
            return section_tool.call(step.tickers[0], _year(step.fiscal_years[0]),
                                     step.item), extra
        if step.tool == "calculate":
            res, extra["notes"] = run_calculate(step, prior)
            return res, extra
        if step.tool == "list_companies":
            return companies_tool.call(step.sector), extra
        raise ValueError(f"unknown tool {step.tool!r}")
    except Exception as e:   # LLM-made arguments must never crash /ask
        return ToolResult.fail(f"{step.tool}: bad arguments: {type(e).__name__}: {e}"[:300]), \
            extra


def _call_detail(step: PlanStep, res: ToolResult, extra: dict) -> dict:
    detail = {"tool": step.tool,
              "args": step.model_dump(exclude_defaults=True, exclude={"tool"}),
              "ok": res.ok, "error": res.error, **extra}
    if step.tool == "sql_query":
        detail["rows"] = sum(1 for d in res.data if "metric" in d)
    elif step.tool in ("search_filings", "get_section"):
        detail["chunks"] = len(res.data)
    elif step.tool == "calculate":
        detail["results"] = [{k: d[k] for k in ("ticker", "name", "result", "source_id")}
                             for d in res.data]
    else:
        detail["rows"] = len(res.data)
    return detail


# ---- nodes -----------------------------------------------------------------------------

def _add(a: Tokens, b: Tokens) -> Tokens:
    return Tokens(prompt=a.prompt + b.prompt, completion=a.completion + b.completion)


def _stop_check(plan: list[PlanStep], idx: int, tool_calls: int, signatures: list[str],
                same_retry: bool = False) -> tuple[str | None, str | None]:
    """(stop_reason, flag) before executing plan[idx]; (None, None) to go on."""
    if idx >= len(plan):
        return "done", None
    if tool_calls >= MAX_TOOL_CALLS:
        return "tool cap", FLAG_CAP
    if plan[idx].signature() in signatures and not same_retry:
        return "repeated call", FLAG_REPEAT
    return None, None


def plan_node(state: AgentState) -> dict:
    steps, tokens = planner.plan(state["question"])
    trace = [*state["trace"], Step(name="plan", detail={
        "steps": [s.model_dump(exclude_defaults=True) for s in steps]})]
    stop, flag = _stop_check(steps, 0, 0, [])
    return {"plan": steps, "trace": trace, "tokens": _add(state["tokens"], tokens),
            "stop_reason": stop, "flags": [*state["flags"], *([flag] if flag else [])]}


def execute_node(state: AgentState) -> dict:
    idx = state["step_idx"]
    step = state["plan"][idx]
    res, extra = dispatch(step, state["tool_results"])
    n = len(state["tool_results"])
    step_results = {**state["step_results"], idx: [*state["step_results"].get(idx, []), n]}
    return {"tool_results": [*state["tool_results"], res],
            "step_results": step_results,
            "tool_calls": state["tool_calls"] + 1,
            "signatures": [*state["signatures"], step.signature()],
            "trace": [*state["trace"], Step(name="tool_call",
                                            detail={"step": idx, **_call_detail(step, res,
                                                                                extra)})]}


def grade_node(state: AgentState) -> dict:
    idx = state["step_idx"]
    step = state["plan"][idx]
    res = state["tool_results"][-1]
    g, tokens = grader.grade(step, res)
    results = list(state["tool_results"])
    if g.keep_ids is not None:   # keep only the passages the grader found relevant
        keep = set(g.keep_ids)
        results[-1] = ToolResult(ok=res.ok, error=res.error,
                                 data=[d for d in res.data if d.get("source_id") in keep],
                                 sources=[s for s in res.sources if s.source_id in keep])
    plan, retries = list(state["plan"]), dict(state["retries"])
    used = retries.get(idx, 0)
    retrying = g.retry_step is not None and used < MAX_RETRIES
    if retrying:
        plan[idx] = g.retry_step
        retries[idx] = used + 1
        next_idx = idx
    else:
        next_idx = idx + 1
    same_retry = retrying and g.retry_step.signature() == step.signature()
    stop, flag = _stop_check(plan, next_idx, state["tool_calls"], state["signatures"],
                             same_retry)
    detail = {"step": idx, "ok": g.ok, "reason": g.reason, "retry": retrying}
    if g.keep_ids is not None:
        detail["kept"] = len(results[-1].data)
    if g.retry_step is not None and not retrying:
        detail["retry_skipped"] = f"max {MAX_RETRIES} retries used"
    return {"tool_results": results, "plan": plan, "retries": retries, "step_idx": next_idx,
            "stop_reason": stop, "flags": [*state["flags"], *([flag] if flag else [])],
            "trace": [*state["trace"], Step(name="grade", detail=detail)],
            "tokens": _add(state["tokens"], tokens)}


def answer_node(state: AgentState) -> dict:
    tokens, flags = Tokens(), list(state["flags"])
    if not evidence.evidence_items(state["tool_results"]):   # FR-12: nothing usable
        draft = Draft(not_found=True)
        detail = {"not_found": True, "reason": "no usable evidence"}
    else:
        try:
            draft, tokens = answerer.answer(state["question"], state["tool_results"],
                                            state.get("feedback"))
            detail = {"claims": len(draft.claims), "not_found": draft.not_found}
        except LLMError as e:
            draft = Draft(not_found=True)
            flags.append(f"answer writer failed: {e}"[:300])
            detail = {"not_found": True, "reason": "answer writer failed"}
    detail["attempt"] = state["answer_retries"] + 1
    return {"draft": draft, "flags": flags, "tokens": _add(state["tokens"], tokens),
            "trace": [*state["trace"], Step(name="answer", detail=detail)]}


def verify_node(state: AgentState) -> dict:
    draft = state["draft"]
    if draft is None or draft.not_found or not draft.claims:
        return {"feedback": None}
    vr = verifier.verify(draft, state["tool_results"])
    failed = [{"claim": c.text, "reason": r} for c, r in vr.failed_claims]
    trace = [*state["trace"], Step(name="verify", detail={"ok": len(vr.ok_claims),
                                                          "failed": failed})]
    if not vr.failed_claims:
        return {"trace": trace, "feedback": None}
    if state["answer_retries"] < MAX_ANSWER_RETRIES:
        feedback = "These claims failed verification; fix or drop them:\n" + "\n".join(
            f"- {f['claim']} ({f['reason']})" for f in failed)
        return {"trace": trace, "feedback": feedback,
                "answer_retries": state["answer_retries"] + 1}
    flags = [*state["flags"], *(f"removed unverified claim: {c.text}" for c, _ in
                               vr.failed_claims)]
    return {"trace": trace, "feedback": None, "flags": flags,
            "draft": Draft(claims=vr.ok_claims, not_found=not vr.ok_claims)}


def _after_grade(state: AgentState) -> str:
    return "answer" if state.get("stop_reason") else "execute"


def _after_verify(state: AgentState) -> str:
    return "answer" if state.get("feedback") else END


@lru_cache
def build_graph():
    g = StateGraph(AgentState)
    g.add_node("plan", plan_node)
    g.add_node("execute", execute_node)
    g.add_node("grade", grade_node)
    g.add_node("answer", answer_node)
    g.add_node("verify", verify_node)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", _after_grade, {"execute": "execute", "answer": "answer"})
    g.add_edge("execute", "grade")
    g.add_conditional_edges("grade", _after_grade, {"execute": "execute", "answer": "answer"})
    g.add_edge("answer", "verify")
    g.add_conditional_edges("verify", _after_verify, {"answer": "answer", END: END})
    return g.compile()


def initial_state(question: str) -> AgentState:
    return AgentState(question=question, plan=[], step_idx=0, tool_results=[], step_results={},
                      retries={}, tool_calls=0, signatures=[], draft=None, answer_retries=0,
                      feedback=None, flags=[], stop_reason=None, trace=[], tokens=Tokens())


def run_agent(question: str) -> AskResponse:
    start = time.perf_counter()
    state = build_graph().invoke(initial_state(question), {"recursion_limit": 60})
    draft = state.get("draft")
    if draft is None or draft.not_found or not draft.claims:
        text, citations = NOT_FOUND, []
    else:
        text, citations = evidence.render_answer(draft.claims, state["tool_results"])
    steps = [*state["trace"], Step(name="flags", detail={
        "flags": state["flags"], "stop_reason": state.get("stop_reason"),
        "tool_calls": state["tool_calls"]})]
    return AskResponse(answer=text, citations=citations, steps=steps, tokens=state["tokens"],
                       latency_ms=int((time.perf_counter() - start) * 1000))
