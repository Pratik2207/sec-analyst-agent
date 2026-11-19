# Phase 5 report: Evals

Date: 2026-11-19 · Range: `phase-5-start..phase-5-done` · Tracks: 2 (parallel worktrees, merged)

**Status: built and verified; the full eval run and the dataset approval are DEFERRED (user).**
You chose to ship first (Phase 6) and run the evals later. Everything needed to run them is
in place and tested. AC1 (your approval) and AC2/AC3's measured values come from that run.

## What was built
- **Contract:**
  - `evals/schema.py`: DatasetItem with path-safe ids; RunResult.
  - `evals/systems.py`:
    - The agent system, which is the full `/ask` pipeline, and the baseline. Both return the evidence used, for faithfulness scoring.
    - The ablations: `agent:no_sql` runs end to end and also bypasses the fast path. no_reranker, no_sparse and no_headers are scored as retrieval recall@10, the last against a `filings_noheader` collection.
  - Ablation switches in `src`.
  - `run_agent_traced` and `answer_traced`.
- **Dataset (track-a):**
  - `evals/dataset.jsonl` has 120 questions: 40 number, 40 text, 30 multihop, 10 unanswerable. They are spread over the 10 pilot companies and FY2023–25.
  - `evals/build_dataset.py` computes every number and multihop gold from `evals/data/facts_pilot.json`.
  - `evals/validate_dataset.py` checks the golds against the facts, and checks that each text gold's key phrases appear in a real chunk.
  - `evals/dataset_review.md` is the review sheet.
- **Runner (track-b):** `evals/run_eval.py`.
  - **Resumable:** every run, judgment and retrieval is cached.
  - **Stale caches are not reused:** a cached result is used only for the same question, gold answer and model configuration.
  - **Phases:** systems → judge (qwen3:8b) → retrieval ablations → report.
  - **`--per-type quick` stratified subset:** 32 questions covering all 10 companies, about 1.5 h.
- **Scorers** (`evals/scoring/`):
  - number match within ±1%, sign-aware and scale-aware
  - refusal detection
  - an LLM judge
  - local RAGAS-style faithfulness
  - citation accuracy, approximated as (ticker, FY) ∈ gold sources
  - recall@10
  - latency p50/p95
  - a report with the NFR-1…5 PASS/FAIL table and a failure list with heuristic causes

## Verified
- **Runner end to end on real services** (6-question sample): it works; fast-path p50 is 3.6 s (NFR-4 PASS on the sample).
- **Judge speed and sanity:** qwen3:8b takes 8–19 s per call and rules a right and a wrong answer correctly. The full run is therefore about 6 h, not the 9–14 h estimated.
- **Golds checked independently by the tester:**
  - all 40 number golds against the facts
  - all 30 multihop golds recomputed from the question meaning
  - recall@10 golds: the key phrases are present in chunk *bodies*, so the no-headers ablation isn't penalised
- **Tests: 846 unit tests passed; the eval integration tests passed,** including a quick run on the real dataset with stubbed systems and a real-Qdrant no-headers indexing check.

| Req / AC | Status | Evidence |
|---|---|---|
| AC1 / X-5 dataset 40/40/30/10, validator, user approval | PARTIAL: approval DEFERRED (user) | the validator passes; golds independently verified |
| AC2 / FR-17 one command runs agent + baseline + 4 ablations, report per type | MET (code); run DEFERRED (user) | sample run on live services; quick run with stubs on the real dataset |
| AC3 NFR-1…5 target vs measured, PASS/FAIL | MET (code); values DEFERRED (user) | NFR logic tests, including the boundaries |
| X-6 ablations | MET (after fix) | no_sql now really excludes SQL; retrieval ablations scored by recall@10 |

## Reviews
- **Code review: CHANGES REQUIRED.** One high finding, fixed: `agent:no_sql` still answered number questions through the fast path, which is a SQL lookup, so the ablation would have shown that SQL adds nothing.
- **Mediums, all fixed:**
  - refusal paraphrases, which were biased against the baseline
  - faithfulness context truncation dropping cited evidence
  - a retrieval cache that ignored edited questions
  - 7 sector-wide questions whose golds would break at 50 companies; they now name the pilot companies
- **Lows, fixed:**
  - a negative gold needs loss/decline wording
  - a percent never matches a USD gold
  - model-config stamp on cached runs
  - stale results aren't scored
- **Low, kept:**
  - The `search_use_reranker` and `search_use_sparse` settings are kept. They work, they're tested, and they allow an end-to-end agent ablation later.
- **Tester failures, all fixed:** the no_sql bypass, explicit scales being re-scaled ("$3.9 million" matched a trillion gold), and answers with a value counted as refusals.
- **Security review: no issues.** Hardening applied: path-safe dataset ids. Deferred to Phase 6: a warning at API startup when an ablation switch is set outside its default.

## What's left for you (deferred)
1. **Approve the dataset:** review `evals/dataset_review.md`. Reply "approved", or list ids to change.
2. **Run the evals** in your own terminal. The quick run is about 1.5 h:
   ```
   uv run python -m evals.run_eval --run-id pilot-v1 --per-type quick --skip-noheader
   ```
   - Drop `--per-type quick` for all 120 questions (about 6 h, resumable).
   - The report goes to `evals/results/pilot-v1/report.md`.

## Deviations from the plan
- **Faithfulness:** RAGAS-style, implemented locally with the judge. The `ragas` package was not used, because it pulls LangChain/OpenAI defaults into a local-only project.
- **Citation accuracy:** approximated as (ticker, FY) ∈ gold sources.
- **Retrieval ablations** are measured at the retrieval level (recall@10); only no_sql runs the agent end to end. This is a deliberate choice for this GPU.
- **Quick stratified subset:** added because a full run is about 6 h on this hardware.
- **The eval run happens after Phase 6,** by your choice.
