# Eval report: pilot-v1

Date: 2026-11-20. Dataset: `D:\Code\SEC Anaylst\evals\dataset.jsonl` (32 questions: number 10, text 10, multihop 8, unanswerable 4).

## Headline: agent vs baseline

| Type | System | N | Accuracy | Refusal acc. | Citation acc. | Faithfulness | p50 | p95 | Tokens/q |
|---|---|---|---|---|---|---|---|---|---|
| number | agent | 10 | 90.0% | n/a | 100.0% | 100.0% | 0.7 s | 32.4 s | 928 |
| number | baseline | 10 | 60.0% | n/a | 85.7% | 100.0% | 21.2 s | 36.7 s | 2,384 |
| text | agent | 10 | 55.0% | n/a | 100.0% | 100.0% | 120.7 s | 189.3 s | 5,575 |
| text | baseline | 10 | 75.0% | n/a | 100.0% | 100.0% | 33.1 s | 92.4 s | 2,890 |
| multihop | agent | 8 | 75.0% | n/a | 100.0% | 100.0% | 118.1 s | 197.2 s | 6,477 |
| multihop | baseline | 8 | 6.2% | n/a | 100.0% | 100.0% | 25.3 s | 29.4 s | 2,655 |
| unanswerable | agent | 4 | 100.0% | 100.0% | n/a | n/a | 11.9 s | 41.4 s | 916 |
| unanswerable | baseline | 4 | 100.0% | 100.0% | n/a | n/a | 15.1 s | 17.5 s | 1,842 |
| overall | agent | 32 | 76.6% | 100.0% | 100.0% | 100.0% | 52.4 s | 181.2 s | 3,766 |
| overall | baseline | 32 | 56.2% | 100.0% | 94.1% | 100.0% | 23.6 s | 71.3 s | 2,542 |

Multihop numeric match (items with a gold_value): agent 62.5%; baseline 0.0%.

Refusal accuracy is measured on unanswerable questions; a refusal on an answerable question scores 0. Citation accuracy approximates "source contains the claim" by (ticker, fiscal_year) in the gold sources. Latency excludes errored runs.

## Ablations

### End to end

| System | Type | N | Accuracy | p50 | p95 | Tokens/q |
|---|---|---|---|---|---|---|
| agent:no_sql | number | 10 | 30.0% (agent 90.0%) | 126.9 s | 154.0 s | 8,406 |
| agent:no_sql | multihop | 8 | 12.5% (agent 75.0%) | 149.9 s | 259.4 s | 8,034 |
| agent:no_sql | overall | 18 | 22.2% (agent 76.6%) | 138.7 s | 237.5 s | 8,241 |

### Retrieval recall@10

| Config | Questions | Hits | Recall@10 |
|---|---|---|---|
| full | 10 | 10 | 100.0% |
| no_reranker | 10 | 8 | 80.0% |
| no_sparse | 10 | 7 | 70.0% |
| no_headers | n/a | n/a | n/a |

## NFR check

| NFR | Target | Measured | Status |
|---|---|---|---|
| NFR-1 | agent accuracy >= 80%; agent - baseline >= 25 pts on multihop | accuracy 76.6%; multihop gap +68.8 pts | **FAIL** |
| NFR-2 | agent faithfulness >= 95% | 100.0% | **PASS** |
| NFR-3 | recall@10 (full config) >= 85% | 100.0% | **PASS** |
| NFR-4 | fast-path p50 < 5 s | 1.2 s (n=14) | **PASS** |
| NFR-5 | agent multihop p50 < 60 s, p95 < 120 s | p50 118.1 s, p95 197.2 s | **FAIL** |

## Agent failures (9)

By cause: judge-incorrect 3, wrong number 3, refused but answerable 2, judge-partial 1.

| QID | Type | Cause | Question | Answer excerpt |
|---|---|---|---|---|
| num-014 | number | refused but answerable | How much did Qualcomm spend on R&D in FY2025? | Not found in the filings. |
| txt-005 | text | judge-partial | What agreement did AMD sign with OpenAI in 2025? | In October 2025, AMD entered into a product purchase agreement with OpenAI OpCo, LLC, to deploy 6 gigawatts of AMD GPUs [1]. |
| txt-010 | text | refused but answerable | Why did Intel stop paying dividends in 2024? | Not found in the filings. |
| txt-014 | text | judge-incorrect | What happened to Qualcomm's licensing royalties from Huawei in fiscal 2025? | Qualcomm's revenue for fiscal year 2025 (period ending 2025-09-28) was $44.28 billion. |
| txt-023 | text | judge-incorrect | Where does Bank of America say it has concentrations of credit risk (FY2024)? | Bank of America's net income for fiscal year 2024 (period ending 2024-12-31) was $27.13 billion. |
| txt-031 | text | judge-incorrect | Which Pfizer drugs were selected for Medicare price setting under the IRA, per its FY2024 10-K? | Eliquis was selected for Medicare price setting under the IRA, with the price effective January 1, 2026 [1]. |
| mh-009 | multihop | wrong number | How much larger were JPMorgan Chase's total assets than Bank of America's at the end of 2024? | Bank of America's total assets at the end of 2024 were $3,261,519,000,000 USD (period ending 2024-12-31) [1]. JPMorgan Chase's total assets at the end of 2024 w... |
| mh-022 | multihop | wrong number | Which had the higher return on assets in FY2025 (net income divided by year-end total assets): JPMorgan Chase or Bank of America? | JPMorgan Chase had a return on assets of 0.0128925 in FY2025 (period ending 2025-12-31) [1]. |
| mh-030 | multihop | wrong number | By how many percentage points did Merck's R&D-to-revenue ratio change from 2023 to 2024? | Merck's R&D-to-revenue ratio increased by 22.83 percentage points in FY2024 [1][2] |

## Run metadata

- run_id: pilot-v1
- date: 2026-11-20
- dataset: D:\Code\SEC Anaylst\evals\dataset.jsonl
- n_items: 32
- counts: {'number': 10, 'text': 10, 'multihop': 8, 'unanswerable': 4}
- systems: agent, baseline, agent:no_sql
- models: fast=qwen3:1.7b, planner=qwen3:4b-instruct (think=False), grader=qwen3:1.7b, answer=qwen3:4b-instruct, judge=qwen3:8b, embed=BAAI/bge-small-en-v1.5, sparse=Qdrant/bm25, rerank=Xenova/ms-marco-MiniLM-L-6-v2
- settings: baseline_k=8, llm_num_ctx=8192, llm_timeout_s=300.0, collection=filings
- ablations: {'agent:no_sql': ({'agent_disabled_tools': ['sql_query']}, ('number', 'multihop'))}
- faithfulness_systems: agent, baseline
- systems_cache_hits: 0
- systems_ran: 82
- judge_cache_hits: 0
- judge_calls: 74
- judge_failed: 0
- retrieval_cache_hits: 0
- retrieval_errors: 0
- missing_results: 0
