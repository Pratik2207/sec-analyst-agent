# Phase 4 report: Agent loop

Date: 2026-11-19 · Range: `phase-4-start..phase-4-done` · Tracks: 2 (parallel worktrees, merged)

## What was built
- **Contract (main):**
  - `state.py`: a flat `PlanStep`, plus `Claim`, `Draft`, `VerifyResult`, `AgentState`, and caps of 8 tool calls and 2 retries.
  - `llm.py`: `chat_json`. It uses structured output, `num_ctx` 8192 and a 300 s timeout, and any failure becomes `LLMError`.
  - `evidence.py`: evidence items, escaped rendering, number parsing and matching, calc→filing citation resolution, and answer rendering.
- **track-a, the loop:**
  - `planner.py`: one structured-output call produces the whole plan, which code normalises with enums and validates.
  - `grader.py`: code checks plus a qwen3:1.7b relevance and rewrite pass for searches.
  - `graph.py`: a LangGraph loop of plan → execute → grade → retry/next → answer → verify → re-answer once.
    - The dispatcher builds the SQL in code; the LLM never writes SQL.
    - calculate runs once per ticker over `<metric>_<year>` variables.
    - Caps, repeat detection, partial answers and the not-found handling all live here.
- **track-b, answers:**
  - `answerer.py`: structured claims with `source_ids`, filtered by company, with citation repair from facts/calcs only.
  - `verifier.py`: code only. It checks numbers within rounding, and the **direction** of change claims.
- **Main:** `/ask` sends questions to the fast path or the agent, with the route step and the token sums in the response.

## Design decisions made from live runs
1. **The planner uses `qwen3:4b-instruct`, not the thinking build.** Thinking `qwen3:4b` took 193 s and 2.6k completion tokens for the same 3-step plan, against 35–60 s for instruct. This deviates from PRD §5.1 ("thinking on for the planner"), which can't fit the 60 s multi-hop budget on a 4 GB GPU.
2. **The SQL is code-built from enum-validated plan fields.** This is more reliable for a 4B model, and it closes the Phase 3 citation-forgery path (confirmed by the security review).
3. **Per-ticker calculate.** One formula runs for every company, so the semiconductor question needs 3 tool calls instead of 16 or more.
4. **Direction labels plus a direction check.** On the first live run, the 4B answer model said all four chipmakers *raised* R&D share. The truth is **none** did. Code now labels each change "increased"/"decreased" in the evidence, and the verifier rejects claims whose direction contradicts the change calc. The check is clause-scoped, ignores negated clauses and comparatives, and takes the year from the clause.
5. **"Which/who" questions require a direct answer.** One live run listed each company's correct changes but never said "none". For these questions the answer schema now requires an `answer` field. It sorts first, so the model writes the conclusion first.
6. **`num_ctx` 8192.** Ollama's 4096 default overflowed on multi-hop evidence.

## Live results (pilot data, `/ask`)
| Question | Result | Time |
|---|---|---|
| Which semis raised R&D share while gross margin fell, FY24→FY25? | **"None of the semiconductor companies…"** + verified per-company changes in percentage points, 8 sec.gov citations | 61–107 s (6 of 7 runs passed; see below) |
| NVIDIA revenue FY2030 | "Not found in the filings." (fast path) | 6.8 s |
| Bank with the highest FY2025 net income | JPM, $57.05B, cited | 23.7 s |
| LLY revenue FY23→FY25 | $34.12B → $65.18B, cited | 25.4 s |
| NVDA vs AMD R&D FY2025 | $12.91B vs $8.09B, cited | 22.4 s |
| AMD gross margin change 2024 (text) | Revenue-mix explanation from Item 7, cited | 106 s |
| NVIDIA supply-chain risks FY2025 (text) | 4 NVDA citations | 135 s |
| JPM vs GS R&D; Acme Robotics | Not found (correct) | 18–45 s |

## Tests
- **Unit: 646 passed.**
- **Integration (full run, 21 min): 128 of 129 passed.**
  - The failure was `test_live_semis_multihop`, inside the long run where several models swap on the 4 GB GPU.
  - Its output wasn't captured. It passed in 6 other runs, including 3 back to back right after, with identical answers.
  - It's recorded as an **unexplained flake**. Phase 5 runs the question set repeatedly and will measure stability.
- The tester added 49 tests: cap, retry and repeat edge cases, planted wrong numbers and wrong directions through the real graph, FR-12 variants, dispatcher SQL against the real DB, injection, and 5 live questions.

| Req / AC | Status | Evidence |
|---|---|---|
| AC1 semis question correct + cited, calculate in steps | MET (after fix) | the "none" conclusion and correct per-company changes; 3 tool calls (sql, calc, calc) |
| AC2 NVIDIA FY2030 → not found | MET | fast path and agent tests |
| AC3 cap 8 / repeat stop / ≤ 2 retries | MET | `tests/agent_loop` and the tester's edge cases |
| AC4 verifier removes and flags a planted wrong number | MET | also catches a planted wrong direction |
| AC5 every claim's citation resolves to a tool source | MET (after fix) | claims with no filing citation now fail verification |
| FR-7, FR-10, FR-12, FR-13, FR-14, NFR-7 | MET | see above |
| FR-11 | MET | every rendered claim carries a filing citation |

## Reviews
- **Code review: CHANGES REQUIRED.** It had 3 high findings, all fixed:
  1. Citation repair could "verify" a wrong number from a chunk's incidental numbers (e.g. "Form 10-K"). Repair now uses facts and calcs only, and chunk text skips labels.
  2. A failed or empty re-answer threw away claims that had already passed, and the "answer writer failed" flag never fired. Verified claims are now kept, and `LLMError` propagates so the flag is real.
  3. The direction check rejected correct comparisons ("AMD raised more than INTC"). Multi-company and comparative clauses are now skipped.
- **Medium findings, all fixed:** year-scoped direction checks; "made up half" no longer counts as a rise; a grader rewrite that repeats an earlier call cancels the retry instead of stopping the plan.
- **Low findings, fixed:**
  - "N points" magnitudes are now checked.
  - The planner parse is guarded.
  - Ollama has a client timeout.
- **Security review:** one low finding, fixed. Model-written `[n]` markers are stripped, so they can't point at unverified sources. Two hardening notes were also fixed: the timeout and the planner guard.
- **Tester failures, all fixed:**
  - a negated true claim ("did not raise") was wrongly rejected
  - case-sensitive company names ("Nvidia")
  - a claim citing only `companies` rendered with no citation
  - the missing direct answer

## Open low items (decided)
| Item | Decision |
|---|---|
| Partial coverage isn't flagged (the pharma answer silently left out net income) | Phase 5: the eval scores coverage |
| Direction-check synonym gaps ("R&D intensity rose") | Skipped: rare; the main words are covered |
| Text-question latency 106–135 s | Phase 5 measures NFR-5 |
| Error strings in API traces; also escape `&` in evidence | Phase 6 packaging (the API is local and single-user today) |
| Baseline citation parsing and labels (from Phase 3) | Phase 5 |

## Deviations from the plan
- **The planner is non-thinking** (decision 1).
- **Extra code-side safeguards** (decisions 4 and 5), added because of measured 4B-model failures.
- **The test fixture `ctx_8k`** in track-b's live test is now redundant (`num_ctx` is a setting) but harmless.
- **The integration flake,** described above.
