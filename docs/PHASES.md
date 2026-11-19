# Phases: SEC Filings Analyst Agent
PRD: docs/PRD.md

## Decisions and assumptions (agreed before planning, 2026-11-19)
- **Hardware:** GTX 1650 with 4 GB VRAM and 23 GB RAM, not the PRD's 8 GB GPU. The user chose smaller models (below). Every model name is set in `.env` and `config/settings.py`, so a model can be swapped without code changes.

  | Role | PRD model | v1 model on this machine |
  |---|---|---|
  | Planner, answer writer | qwen3:8b | **qwen3:4b** (thinking on) |
  | Grader, query rewriter, fast path | qwen3:4b | **qwen3:1.7b** (thinking off) |
  | Eval judge (offline, so latency doesn't matter) | qwen3:8b | qwen3:8b (already pulled) |
  | Dense embeddings | bge-base-en-v1.5 (768) | **bge-small-en-v1.5 (384)** |
  | Reranker | bge-reranker-v2-m3 | **bge-reranker-base** |
  | Sparse | Qdrant/bm25 (fastembed) | same |
- **PostgreSQL:** no server is running on this machine. DBeaver is only the client. Postgres 16 runs as a service in this project's `docker-compose.yml`, on host port **5433**. It is a new, separate server with its own `sec_analyst` database, and this project never uses or touches any existing DBeaver connection. Add a new DBeaver connection to `localhost:5433`. *(Confirm at approval.)*
- **Tracing:** full self-hosted Langfuse v3 stack, added in Phase 6.
- **Eval set:** Claude drafts the questions with gold answers and sources from the loaded data, and the user reviews them. The user, or someone else, writes about 20 of them (PRD §12).
- **Agent framework:** LangGraph, as named in the PRD's §5 table.
- **Project root:** this folder. Python is 3.12, managed by uv.
- **Company scope:** the build follows PRD §11. Phases 1–5 run on **10 pilot companies** (at least 4 semiconductors, plus banks and pharma). Phase 6 scales to all 50. `config/companies.yaml` lists all 50, with a `pilot: true` flag on the first 10.
- **Disk:** D: has 48 GB free and C: has 31 GB. Docker images (Langfuse v3 is about 4 GB) go on C: through Docker Desktop. `data/` and the HF model cache stay on D:.

## Requirement IDs
The PRD's functional requirements already have IDs (FR-1…FR-20). The non-functional rows got new IDs NFR-1…NFR-12. Requirements stated only in the PRD's prose got new IDs X-1…X-8. A ✎ in the table marks a requirement that was rewritten to make it testable.

## Requirements
| ID | Requirement | Acceptance criterion | Phase |
|---|---|---|---|
| FR-1 | Download 10-Ks from EDGAR with a compliant User-Agent, ≤ 10 req/s | Every pilot company × FY2023–25 10-K is in `data/raw/`. Unit test: the rate limiter never exceeds 10 req/s and the User-Agent header comes from `SEC_USER_AGENT`. A re-run reads the cache and makes 0 network calls | 2 |
| FR-2 | XBRL companyfacts → key metrics in PostgreSQL | revenue, gross_profit, rd_expense, operating_income, net_income and total_assets are loaded where the sector reports them. Loads use `INSERT … ON CONFLICT DO UPDATE` | 1 |
| FR-3 | Map XBRL tags to canonical metrics | `metric_map.yaml` supports ordered fallbacks. A unit test checks that `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax` both map to `revenue` | 1 |
| FR-4 | Split each 10-K into Items 1, 1A, 7, 7A, 8, then by subheading | Parsed JSON for every pilot filing has Items 1, 1A and 7 found. Each Item is split by subheading, and Risk Factors have one entry per risk | 2 |
| FR-5 | Chunks with context headers and metadata; dense + sparse indexing in Qdrant | Every chunk is ≤ 800 tokens and starts with the `[Company \| 10-K \| FYxxxx \| Item \| Section]` header. The payload matches PRD §7.2. Points carry both `dense` and `sparse` vectors | 2 |
| FR-6 | Hybrid search with filters and reranking | `hybrid_search` takes filters on ticker, sector, fiscal_year and item, retrieves the top 30 and reranks to the top 8. The PRD §11 check: the right chunk is in the top 10 for ≥ 16 of 20 manual questions | 2 |
| FR-7 | Agent plans sub-steps and picks a tool per step | The plan is produced as Ollama structured output (JSON schema). The trace shows ≥ 2 steps and the chosen tools for the semiconductor multi-hop question | 4 |
| FR-8 | Read-only SQL tool | `sql_query` connects as `agent_reader`. Non-SELECT statements and multiple statements are rejected. INSERT is refused by the DB role itself (tested). Each returned row includes `accession_no` | 1 |
| FR-9 | Calculator tool for all math | It evaluates arithmetic on named values in a restricted AST evaluator. Tests show that imports, attribute access, calls and names not passed in are all rejected | 3 |
| FR-10 | Grader plus query rewrite, max 2 retries per step | Unit test with a stubbed LLM: weak results are retried at most 2 times, then the loop moves on | 4 |
| FR-11 | Every claim cited (ticker, form, FY, section, EDGAR URL) | Every sentence in the answer carrying a number or a fact has ≥ 1 citation that resolves to a tool result's source ID | 4 |
| FR-12 | Answer "not found in the filings" when evidence is missing | Questions such as "NVIDIA revenue FY2030" return the not-found answer with no invented number | 4 |
| FR-13 | Verifier checks cited numbers against the source | Each cited number is matched against its tool output, within rounding. One retry, then the failed claim is removed and flagged in the response | 4 |
| FR-14 | `POST /ask` returns answer, citations, steps, tokens and latency | API test checks that every field exists with the right type (Pydantic model) | 4 |
| FR-15 | Streamlit UI: chat, sources panel, expandable trace | Running `streamlit run ui/app.py` lets you ask a question and see the answer, the clickable source links and the step trace (checked by a smoke test plus a manual check) | 6 |
| FR-16 | Naive RAG baseline on the same corpus | `naive_rag.answer(q)` does top-k dense search, then a single LLM call, and returns the same response shape as `/ask` | 3 |
| FR-17 | Eval runner scores both systems and writes a report | One command, `uv run python -m evals.run_eval`, writes `evals/results/<date>/report.md` with results per question type | 5 |
| FR-18 | Fast path for single-fact questions | The router sends a single-metric/company/year question down the fast path: one tool call plus the answer, with no planner | 3 |
| FR-19 | Stream agent steps to the UI | The UI shows each step as it finishes, through a streaming endpoint (SSE) | 6 |
| FR-20 | 10-Q filings | **Out of scope for v1** (PRD §2 lists it as v2) | — |
| NFR-1 | Accuracy ≥ 80% for the agent; ≥ +25 points over naive RAG on multi-hop | Measured by the eval runner and reported as PASS/FAIL ✎ (the PRD calls these "starting goals", so a miss is reported and is not a hard blocker) | 5 |
| NFR-2 | Faithfulness ≥ 95% | RAGAS faithfulness on a local judge, shown in the report | 5 |
| NFR-3 | Recall@10 ≥ 85% on gold chunks | Shown in the report | 5 |
| NFR-4 | Fast-path latency p50 < 5 s | p50 shown in the report ✎ (measured on this laptop with the v1 models) | 5 |
| NFR-5 | Multi-hop latency p50 < 60 s, p95 < 120 s | p50 and p95 shown in the report ✎ (the PRD says "on 8 GB GPU". This is rewritten to: on this laptop, GTX 1650 4 GB, with the v1 models) | 5 |
| NFR-6 | $0 API cost, local models only | A test fails if `anthropic`, `openai` or another non-Ollama LLM client is imported under `src/`, or if an `*_API_KEY` is read under `src/` | 1 |
| NFR-7 | Max 8 agent steps, then a partial answer; stop on repeated identical tool calls | Unit test: a stub LLM that loops ends at 8 calls with a partial answer. A repeated identical call stops the loop early | 4 |
| NFR-8 | Ingestion re-runnable with no duplicates | Running ingest twice leaves the Qdrant point count and the `financial_facts` row count unchanged (integration test) | 2 |
| NFR-9 | Read-only Postgres role, 5 s statement timeout | Integration test: `SELECT pg_sleep(6)` fails with a timeout, and writes fail as `agent_reader` | 1 |
| NFR-10 | Secrets only in `.env`, never committed | `.env` is gitignored and `.env.example` holds only placeholders. A test scans tracked files for secret patterns | 1 |
| NFR-11 | Clean machine: `docker compose up` + one ingest command | From a fresh clone, `docker compose up -d` plus `uv run python -m src.ingest.run_all` gives a working `/ask` | 6 |
| NFR-12 | Every run traced in Langfuse (steps, tool calls, tokens, latency) | After one `/ask`, the Langfuse API returns a trace with spans for each tool call, token counts and the latency | 6 |
| X-1 | Coverage check (PRD §6.1 step 6) | `coverage` command lists any company × year × metric that's missing. For the pilot set it reports 0 gaps for revenue, gross_profit and R&D, or an explained exemption per sector (PRD §11, milestone 1) | 1 |
| X-2 | Sector-specific metric lists (PRD §12) | `config` defines the expected metrics for each sector (banks have no gross profit or R&D). The coverage check and the agent's tool descriptions both use it | 1 |
| X-3 | Fiscal-year handling (PRD §12) | `fiscal_year` comes from the 10-K's DEI `DocumentFiscalYearFocus`, with `period_end` stored separately (test: NVIDIA FY2025 has period_end 2025-01-26). Answers state both | 1 |
| X-4 | Parse-failure fallback (PRD §12) | When Items can't be found, the whole document is chunked recursively and the failure is logged. Tested on a malformed fixture | 2 |
| X-5 | 120-question eval set (PRD §10) | `evals/dataset.jsonl` has 40 single-fact, 40 text, 30 multi-hop and 10 unanswerable questions, each with a gold answer and gold source(s). A validator checks the counts and the schema, and the user has reviewed it | 5 |
| X-6 | Ablations (PRD §10) | The report includes runs without the reranker, without sparse vectors, without context headers, and without the SQL tool | 5 |
| X-7 | Failure analysis (PRD §10) | Wrong answers are grouped by cause, with the top 3 in the README | 6 |
| X-8 | README (PRD §9) | README covers what the project is and why, setup, the results table from the 50-company run, and a demo GIF | 6 |

---

## Phase 1: Walking skeleton + financial facts  [status: done]
Goal: Load XBRL facts for the 10 pilot companies into PostgreSQL, and have `POST /ask` answer one number question from it end to end.
Requirements: FR-2, FR-3, FR-8, NFR-6, NFR-9, NFR-10, X-1, X-2, X-3
Deliverables: `pyproject.toml` (uv); `config/{companies.yaml,metric_map.yaml,settings.py}`; `.env.example`; `docker-compose.yml` (postgres:16 on 5433, qdrant); `sql/schema.sql`; `src/sec_client.py` (shared User-Agent and ≤ 10 req/s limiter); `src/ingest/download_xbrl.py`; `src/ingest/coverage.py`; `src/tools/sql_tool.py`; `src/api/main.py` with a skeleton `/ask` (qwen3:1.7b extracts ticker/metric/year as structured output → SQL template → cited answer); the full folder layout from PRD §9 with empty packages; project `CLAUDE.md` with the exact install, test, lint and run commands.
Acceptance criteria:
1. `docker compose up -d postgres qdrant` comes up healthy, and DBeaver can connect to `localhost:5433/sec_analyst`.
2. `uv run python -m src.ingest.download_xbrl` loads the pilot set. A second run leaves the row count unchanged.
3. `uv run python -m src.ingest.coverage` reports 0 gaps for revenue, gross_profit and rd_expense over FY2023–25, excluding metrics the sector doesn't report (that list lives in config).
4. NVIDIA FY2025 has `period_end = 2025-01-26`.
5. `sql_query` rejects `DELETE`, `SELECT 1; DROP …` and comment-smuggled statements. As `agent_reader`, a write is refused by the DB and `pg_sleep(6)` times out.
6. `POST /ask {"question":"What was Intel's R&D expense in FY2024?"}` returns the value from the DB, with a citation of ticker, 10-K, FY, accession number and EDGAR URL.
7. The forbidden-import test and the secrets test pass. `uv run pytest` and `uv run ruff check` are green.
Unit-test focus: tag mapping and fallbacks, fiscal-year derivation, SQL guard (parsing with sqlglot), the rate limiter.
Integration-test focus: the full XBRL load into a test DB, the role permissions and timeout, `/ask` with Ollama running.
Depends on: none
Tracks: single. This phase creates the folder layout that later tracks own.

## Phase 2: Text pipeline  [status: planned]
Goal: Turn the pilot 10-Ks into section-aware chunks in Qdrant, searchable with hybrid search and reranking.
Requirements: FR-1, FR-4, FR-5, FR-6, NFR-8, X-4
Deliverables: `src/ingest/{download_filings,parse_sections,chunker,index_qdrant}.py`, `src/retrieval/{hybrid_search,reranker}.py`, `scripts/retrieval_check.py`, plus 20 manual retrieval questions in `evals/retrieval_check.jsonl`.
Acceptance criteria:
1. The pilot set (about 30 filings) downloads into `data/raw/`. A re-run makes 0 network requests.
2. For each filing, Items 1, 1A and 7 are found, or the fallback runs and is logged. Risk Factors give one chunk per risk.
3. Every chunk has the context header, at most 800 tokens, about 15% overlap on splits, and the payload from PRD §7.2. MD&A tables become Markdown chunks.
4. Running indexing twice leaves the Qdrant point count the same (deterministic IDs).
5. `hybrid_search(query, filters, k)` combines dense and sparse results with RRF, reranks the top 30, and returns 8. Filters on ticker, sector, fiscal_year and item work.
6. `scripts/retrieval_check.py` finds the right chunk in the top 10 for ≥ 16 of 20 questions.
Unit-test focus: Item and subheading splitting on fixture HTML, risk-per-chunk splitting, token limits and overlap, deterministic IDs, the fallback path.
Integration-test focus: the full ingest of 2 filings into a test Qdrant collection, filtered search, idempotent re-index.
Depends on: Phase 1
Tracks: parallel
  Interface contract (committed before the tracks start):
  - `data/processed/chunks/<accession_no>.jsonl`: one JSON object per chunk, with the PRD §7.2 payload fields, plus `header` and `token_count`. `text` holds the header followed by the body.
  - `src/retrieval/types.py`: `SearchFilters(ticker: str|list|None, sector, fiscal_year: int|list|None, item)` and `SearchHit(id, score, payload: dict)`.
  - `hybrid_search(query: str, filters: SearchFilters|None = None, k: int = 8, use_reranker=True, use_sparse=True) -> list[SearchHit]`. The ablation flags are needed in Phase 5.
  - The point ID is `uuid5(NAMESPACE, f"{accession_no}|{item}|{chunk_index}")`.
  - track-a: download_filings, parse_sections and chunker, which write the chunk JSONL; owns: `src/ingest/download_filings.py`, `src/ingest/parse_sections.py`, `src/ingest/chunker.py`, `tests/ingest_text/`
  - track-b: index_qdrant, hybrid search and the reranker, which read the chunk JSONL and are tested with fixture chunks; owns: `src/ingest/index_qdrant.py`, `src/retrieval/`, `tests/retrieval/`
  - After the merge (main session): `scripts/retrieval_check.py` and the 20-question check.

## Phase 3: Tools, fast path, naive baseline  [status: planned]
Goal: Build all five agent tools, a working fast path for simple questions, and the naive RAG baseline.
Requirements: FR-9, FR-16, FR-18
Deliverables: `src/tools/{search_tool,section_tool,calculator,companies_tool}.py` (plus `sql_tool` from Phase 1); `src/agent/router.py` and `src/agent/fast_path.py`; `src/baseline/naive_rag.py`; `/ask` wired to the router.
Acceptance criteria:
1. Each tool returns JSON with a `source_id` for every item, and the source ID resolves to a citation.
2. `calculate("(rd / revenue) * 100", {"rd": 1, "revenue": 4})` returns 25.0 plus the expression used. Imports, attribute access, `__` names and unknown names are rejected.
3. The router sends "What was Intel's R&D in FY2024?" down the fast path, and sends the semiconductor multi-hop question to the agent (which is still a stub).
4. `naive_rag.answer(q)` returns the same response shape as `/ask`.
Unit-test focus: calculator safety, tool input validation (enums for ticker, item and metric), router classification on a fixture set.
Integration-test focus: each tool against the live pilot data, fast-path latency, a baseline answer on 3 questions.
Depends on: Phase 2
Tracks: parallel
  Interface contract: `src/tools/types.py`, containing `ToolResult(ok: bool, data: list[dict], sources: list[Source], error: str|None)` and `Source(source_id, ticker, form, fiscal_year, section, url, accession_no)`. Each tool exposes `run(**kwargs) -> ToolResult` and a `SPEC`, which is the JSON schema used for Ollama tool calling. The response model `AskResponse` lives in `src/api/schemas.py`.
  - track-a: search, section, calculator and companies tools; owns: `src/tools/` (except `sql_tool.py`), `tests/tools/`
  - track-b: naive RAG baseline; owns: `src/baseline/`, `tests/baseline/`
  - track-c: router and fast path; owns: `src/agent/router.py`, `src/agent/fast_path.py`, `tests/agent_fast/`
  - After the merge: wire `/ask` to the router.

## Phase 4: Agent loop  [status: planned]
Goal: Build the LangGraph agent that plans, calls tools, grades, answers with citations and verifies them, and say "not found" when evidence is missing.
Requirements: FR-7, FR-10, FR-11, FR-12, FR-13, FR-14, NFR-7
Deliverables: `src/agent/{graph,state,planner,grader,answerer,verifier}.py`, `src/agent/prompts/`; `/ask` returns the full `AskResponse` (answer, citations, steps, tokens, latency_ms).
Acceptance criteria:
1. The semiconductor multi-hop question (on the pilot semis) returns a correct, cited answer. Ratios come from `calculate` calls that are visible in the steps.
2. "NVIDIA revenue FY2030" returns "not found in the filings".
3. With a stubbed LLM, the loop caps at 8 tool calls and returns a partial answer. A repeated identical call stops it early. The grader retries a step at most 2 times.
4. The verifier removes and flags a planted wrong number.
5. Every claim in the answer has a citation that resolves to a tool source.
Unit-test focus: graph transitions with a fake LLM, step cap, repeat detection, retry counts, citation resolution, verifier number matching.
Integration-test focus: 5 real questions end to end through `/ask` with Ollama running.
Depends on: Phase 3
Tracks: parallel
  Interface contract: `src/agent/state.py` (`AgentState` TypedDict with question, plan: list[PlanStep], step_idx, tool_results: list[ToolResult], retries: dict[int,int], tool_calls: int, draft: Draft|None, flags); `Draft(text, claims: list[Claim(text, numbers: list[float], source_ids: list[str])])`; `answer(state) -> Draft`; `verify(draft, tool_results) -> VerifyResult(ok_claims, failed_claims)`.
  - track-a: graph, planner, grader and state; owns: `src/agent/graph.py`, `src/agent/state.py`, `src/agent/planner.py`, `src/agent/grader.py`, `src/agent/prompts/plan*`, `src/agent/prompts/grade*`, `tests/agent_loop/`
  - track-b: answer writer and verifier; owns: `src/agent/answerer.py`, `src/agent/verifier.py`, `src/agent/prompts/answer*`, `tests/agent_answer/`
  - After the merge: API wiring and the end-to-end check.

## Phase 5: Evals  [status: planned]
Goal: Score the agent against the naive baseline, plus ablations, on the 120-question set with one command.
Requirements: FR-17, NFR-1, NFR-2, NFR-3, NFR-4, NFR-5, X-5, X-6
Deliverables: `evals/dataset.jsonl` plus a validator; `evals/run_eval.py`; `evals/scoring/` (number exact match within ±1%, LLM judge on qwen3:8b, RAGAS faithfulness, recall@10, refusal accuracy, latency and tokens); `evals/results/<date>/report.md`.
Acceptance criteria:
1. The dataset validator passes (40/40/30/10, schema), and **the user has approved** the questions.
2. `uv run python -m evals.run_eval` runs the agent, the baseline and the 4 ablations, and writes the report with a table per question type.
3. The report states each NFR-1…NFR-5 target next to its measured value, marked PASS or FAIL.
Unit-test focus: the scorers (numeric tolerance, refusal detection, recall@k), the dataset validator.
Integration-test focus: run_eval on a 6-question subset end to end.
Depends on: Phase 4
Tracks: parallel
  Interface contract: one dataset line is `{"id","type":"number|text|multihop|unanswerable","question","gold_answer","gold_value":float|null,"unit","gold_sources":[{"ticker","fiscal_year","item","section","accession_no"}]}`. Each system is a callable `system(question) -> AskResponse`.
  - track-a: dataset drafting and the validator; owns: `evals/dataset.jsonl`, `evals/validate_dataset.py`, `tests/evals_dataset/`
  - track-b: runner, scorers and report; owns: `evals/run_eval.py`, `evals/scoring/`, `tests/evals_scoring/`

## Phase 6: Scale and ship  [status: planned]
Goal: Scale to all 50 companies, then add the Streamlit UI with streaming, Langfuse tracing, the app in Docker Compose, and a README with final results.
Requirements: FR-15, FR-19, NFR-11, NFR-12, X-7, X-8
Deliverables: `ui/app.py`; an SSE endpoint `POST /ask/stream`; `src/observability/tracing.py` (Langfuse callback); Langfuse v3 and app services in `docker-compose.yml`, plus a `Dockerfile`; `src/ingest/run_all.py`; README.
Acceptance criteria:
1. All 50 companies are ingested, and the coverage check is clean or has its gaps explained.
2. A fresh clone works with `docker compose up -d` plus `uv run python -m src.ingest.run_all`, giving a working `/ask` and UI.
3. The UI shows the chat, clickable sources, an expandable trace, and steps that appear live as they run.
4. Every `/ask` call creates a Langfuse trace with tool spans, tokens and latency.
5. The evals are re-run on 50 companies. The README has the results table, the top 3 failure causes, and a demo GIF.
Unit-test focus: SSE event format, the trace span builder.
Integration-test focus: a Streamlit smoke test (AppTest), the Langfuse trace fetched via its API, the compose stack coming up healthy.
Depends on: Phase 5
Tracks: parallel
  Interface contract: SSE events `{"type":"step|token|final","data":…}`; `get_tracer() -> CallbackHandler|None`, which the graph accepts through `config={"callbacks": [...]}`.
  - track-a: Streamlit UI; owns: `ui/`, `tests/ui/`
  - track-b: Langfuse tracing and the stream endpoint; owns: `src/observability/`, `src/api/stream.py`, `tests/observability/`
  - track-c: Docker packaging and run_all; owns: `Dockerfile`, `docker-compose.yml`, `src/ingest/run_all.py`, `tests/packaging/`
  - After the merge: scale to 50 companies, re-run the evals, write the README and failure analysis.
