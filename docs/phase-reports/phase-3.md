# Phase 3 report: Tools, fast path, naive baseline

Date: 2026-11-19 · Range: `phase-3-start..phase-3-done` · Tracks: 3 (parallel worktrees, merged)

## What was built
- **Contract** (`src/tools/types.py`): `Source` (with `.citation()`), `ToolResult`, `tool_spec`, `edgar_index_url`. Every tool exposes `SPEC` (Ollama tool schema) and `call(**kwargs) -> ToolResult`, and every data item's `source_id` resolves to a Source. `sql_tool.call()` builds `xbrl:<accession_no>` filing sources.
- **track-a, tools** (`src/tools/`):
  - `calculator`: AST allow-list evaluator (FR-9).
  - `search_filings`: hybrid search with enum-checked filters.
  - `get_section`: full Item text from the parser output, truncated by tokens. It sends Intel's fallback filings to search instead.
  - `list_companies`: companies plus their sector metrics.
  - Descriptions are short and strict, with enums. Search output is labelled as filing data, not instructions.
- **track-b, naive RAG baseline** (`src/baseline/naive_rag.py`, FR-16): dense top-8, then one LLM call that cites [n] from delimited context, in the same `AskResponse` shape as `/ask`.
- **track-c, router and fast path** (`src/agent/router.py`, `fast_path.py`, FR-18):
  - Plain-code rules (companies, years, multi-hop/explanation/sector/quarter/segment words, two metrics, EPS) decide first.
  - Then qwen3:1.7b extracts {ticker, metric, year} with structured output, and the result is cross-checked against the code-found values.
  - The fast path is one `sql_query` call with enum-checked literals and a templated, cited answer.
- **Main:** `/ask` = `route()` → fast path, or a placeholder for agent questions until Phase 4; latency is end-to-end. The Phase 1 skeleton helpers were removed. `answer_model` is `qwen3:4b-instruct`.

## Results on real data
- "What was Intel's R&D in FY2024?" takes the fast path: "$16.55 billion (period ending 2024-12-28)", cited to the INTC FY2024 10-K. **Warm p50 is 570 ms** (5 runs; NFR-4 target < 5 s).
- The semiconductor multi-hop question routes to the agent by rules alone, with no LLM call.
- **Live router accuracy: 97% (32/33)** on the labelled fixture set; p50 routing is 561 ms.
- **Baseline:** 3/3 live answers cite [n] to sec.gov, at about 36–37 s each (a 3.2k-token prompt on a 4 GB GPU).

## Tests
- **576 passed:** 462 unit and 114 integration. `ruff` is clean.
- The tester added 113 tests: AC1 invariants on all five live tools, 39 more calculator rejections, injection questions against the fast-path SQL, baseline shape compared with a live `/ask`, and sloppy LLM-style arguments.

| Req / AC | Status | Evidence |
|---|---|---|
| AC1 source_id → citation | MET (after fix) | live invariant tests on all 5 tools; the truncation-note bug was fixed |
| AC2 / FR-9 calculator | MET (after fix) | 70+ rejection cases; complex/NaN/huge-int now give ok=False; AC example = 25.0 |
| AC3 / FR-18 router + fast path | MET | both named questions, live; steps are exactly ["route", "sql_query"]; 97% router accuracy |
| AC4 / FR-16 baseline shape | MET | equal to a live /ask response; validates as AskResponse |

## Reviews
- **Code review:** CHANGES REQUIRED. 1 high, fixed: the baseline test still expected the old model name after the model switch; the test was outdated, not the code.
- **Security review:** no confirmed issues.

**Fixed in this phase:**
- **Calculator (both reviews and the tester):**
  - A negative base with a fractional exponent made a complex number, which `abs()` turned into a **silently wrong result** (2.83). Other functions raised uncaught exceptions.
  - A huge integer value and a NaN could also raise.
  - Now every intermediate must be a finite real number, and errors always come back as `ok=False`.
- **Router (code review):** quarter, segment and region questions ("Intel's Q4 2024 revenue", "data center revenue") would have got a cited **full-year consolidated** number. They now go to the agent. Six fixture cases were added: 4 agent, plus 2 fast cases to keep the fixture set balanced.
- **`sql_tool.call` (tester and code review):**
  - The truncation note's source didn't resolve.
  - A failed filings lookup was ignored.
  - Accession numbers that match no loaded filing were cited.
- **Answer model:** the plain `qwen3:4b` tag is thinking-only and ignores `think=False`: about 280 reasoning tokens even for one sentence, 90–170 s baseline answers, and no [n] markers on long answers. It was switched to `qwen3:4b-instruct`, the same size and family. The thinking `qwen3:4b` stays available for the Phase 4 planner.

## Open medium/low items (not fixed; your call)
1. **(low) The fast path answers "Not found in the filings." when the DB lookup fails** (outage or timeout). You chose to keep this behaviour in Phase 1.
2. **(low) Baseline citation parsing** misses "[1, 3]" and "[1-3]", and deduplicated citations don't line up with the [n] numbers in the text.
3. **(low) Citation section labels differ:** "Item 7 | X" in the baseline vs "Item 7 MD&A | X" in the tools. To align in Phase 5.
4. **(low) Tools raise `TypeError` on missing or extra keyword arguments.** The Phase 4 tool dispatcher must catch this.
5. **(low) Float years:** `section_tool` truncates 2024.7, while `search_tool` rejects 2024.0.
6. **(Phase 4) Citation forgery via agent SQL.** `SELECT 999 AS value, '<real accession>' AS accession_no` would be cited. The Phase 4 verifier must check cited numbers against `financial_facts`, or `call()` must cite only accession numbers that are selected as a column.
7. **(Phase 4) Calls to Ollama in the router:** catch transport errors (httpx) as well as response errors, so `/ask` doesn't return a 500. Also escape `</context>`/`<chunk` in chunk text before it goes into prompts.

## Deviations from the plan
- **The tool entry point is `call()`, not `run()`.** `sql_tool.run()` is Phase 1's dict API and is used elsewhere.
- **`answer_model` = `qwen3:4b-instruct`** (see above). It needed a 2.5 GB `ollama pull`.
- **The fix-round edits overlapped the tester's run** and were captured by the auto-checkpoint `ec2408c`. Both were then verified with a full suite run at HEAD.
- **The first full test run after merging track-a stalled.** The builders' live LLM tests were queuing on Ollama, which serves one model at a time on the 4 GB GPU. Later runs were done sequentially.
