# SEC Filings Analyst Agent

Ask plain-English questions about US public companies' 10-K filings and get **sourced** answers.
Every claim carries a citation (company, form, fiscal year, section, EDGAR link), numbers come
from XBRL facts via SQL rather than the model's memory, math goes through a calculator, and when
the filings don't hold the answer it says **"Not found in the filings."**

Runs fully **locally** — open-source models via Ollama and fastembed (ONNX); no API keys, $0 per
question.

> Not investment advice. Educational / research tool over public SEC filings.

## What it can answer

| Question type | Example | How |
|---|---|---|
| Single number | *What was Intel's R&D expense in FY2024?* | Router → **fast path**: one SQL lookup over XBRL facts, ~0.6 s |
| Explanation | *Why did AMD's gross margin change in 2024?* | Agent: hybrid search over 10-K sections → cited answer |
| Multi-hop | *Which semiconductor companies raised R&D as a share of revenue while gross margin fell, FY2024 to FY2025?* | Agent: plan → SQL → per-company calculations → verified, cited answer (**"None of them"**, with each company's changes) |
| Unanswerable | *What was NVIDIA's revenue in FY2030?* | "Not found in the filings." |

## Architecture

```
            Streamlit UI (live steps, sources, trace)          Langfuse (optional tracing)
                     │  SSE /ask/stream                               ▲
                     ▼                                                │ spans, generations
   FastAPI ── router ──► fast path: 1 SQL call + template ────────────┤
                     └─► LangGraph agent: plan → tools → grade → answer → verify
                              │            │             │
             PostgreSQL (XBRL facts)   Qdrant (10-K chunks:   calculator
             read-only role, 5 s       dense bge-small + BM25,  (AST allow-list)
             timeout                   RRF, MiniLM reranker)
   Ingest: SEC EDGAR → XBRL companyfacts → Postgres;  10-K HTML → Items → chunks → Qdrant
```

Two stores, one agent: **numbers live in SQL, text lives in the vector store** — the model never
reads numbers out of text chunks to do math.

Key safeguards (each added after a measured failure of the 4B models — see `docs/phase-reports/`):
- The planner fills a flat plan; **SQL is built by code** from enum-validated fields (never LLM-written).
- `calculate` runs one formula per company over fetched facts; change results are labelled
  "increased/decreased" so the model never interprets a sign.
- The **verifier** (code, no LLM) checks every stated number against the cited source and every
  "rose/fell" against the matching calculation; failing claims get one re-answer, then are removed and flagged.
- "Which/who" questions must lead with a direct answer (structured output).
- Retrieved filing text is treated as data (escaped evidence blocks; markers added by code).

## Results

Run `pilot-v1`, 2026-11-20, on the full 50-company index (150 filings, 37,358 chunks), GTX 1650 4 GB.
It used the **quick stratified subset: 32 of the 120 questions** (10 number, 10 text, 8 multi-hop,
4 unanswerable). The questions are about the 10 pilot companies. Full report:
[`evals/results/pilot-v1/report.md`](evals/results/pilot-v1/report.md).

```
uv run python -m evals.run_eval --run-id pilot-v1 --per-type quick --skip-noheader
```

### Agent vs naive RAG

| Question type | N | Agent accuracy | Baseline accuracy | Agent p50 | Baseline p50 |
|---|---|---|---|---|---|
| Single number | 10 | **90.0%** | 60.0% | 0.7 s | 21.2 s |
| Text / explanation | 10 | 55.0% | **75.0%** | 120.7 s | 33.1 s |
| Multi-hop | 8 | **75.0%** | 6.2% | 118.1 s | 25.3 s |
| Unanswerable (refusal) | 4 | 100.0% | 100.0% | 11.9 s | 15.1 s |
| **Overall** | 32 | **76.6%** | 56.2% | 52.4 s | 23.6 s |

Citation accuracy is 100% for the agent and 94.1% for the baseline; faithfulness is 100% for both.
On multi-hop questions with a numeric gold value, the agent matched 62.5% and the baseline 0%.

### Ablations

| Configuration | Result |
|---|---|
| Agent without the SQL tool | accuracy 22.2% vs 76.6% on number + multi-hop questions (number 30% vs 90%, multi-hop 12.5% vs 75%), at 2–8× the tokens |
| Retrieval, full (dense + BM25 + reranker) | recall@10 100% (10/10) |
| Retrieval without the reranker | recall@10 80% |
| Retrieval without BM25 sparse vectors | recall@10 70% |
| Retrieval without context headers | not run (`--skip-noheader`, which needs a second index) |

### PRD targets

| NFR | Target | Measured | Status |
|---|---|---|---|
| NFR-1 | agent accuracy ≥ 80%; ≥ +25 pts over the baseline on multi-hop | 76.6%; +68.8 pts | **FAIL** (overall accuracy 3.4 pts short; the multi-hop gap passes) |
| NFR-2 | faithfulness ≥ 95% | 100% | PASS |
| NFR-3 | recall@10 ≥ 85% | 100% | PASS |
| NFR-4 | fast-path p50 < 5 s | 1.2 s | PASS |
| NFR-5 | multi-hop p50 < 60 s, p95 < 120 s | p50 118 s, p95 197 s | **FAIL** (one local 4B model on a 4 GB GPU) |

### Top 3 failure causes (9 wrong agent answers)

1. **The router sends questions down the wrong path (3).**
   - Two text questions named a company and a year, so the router treated them as single-number
     lookups. The fast path answered a different question: Qualcomm's FY2025 revenue instead of
     its Huawei royalties, and Bank of America's net income instead of its credit-risk concentrations.
   - In the third, the router's extraction disagreed with itself (MRVL vs QCOM). The agent then
     fetched R&D for the whole sector, and the answer writer missed Qualcomm's $9.04B in those
     rows. It answered "Not found" for a value that is in the database.
2. **The answer writer mishandles multi-hop results (3).**
   - "How much larger were JPMorgan's assets than Bank of America's?": the model did the
     subtraction itself. The verifier removed that unverified number, and the re-answer listed
     both totals without the difference.
   - A return-on-assets comparison gave only JPMorgan's ratio, as a decimal, with no comparison.
   - **The worst case:** Merck's R&D share fell from 50.8% to 28.0%. `calculate` correctly
     returned −22.83 points, but the answer said it "increased by 22.83 percentage points", and
     the verifier's direction check didn't catch it.
3. **Text answers that are incomplete or not retrieved (3).**
   - Intel's 10-Ks are indexed as whole documents (no Item structure). The planner searched with
     Item 1 and Item 7 filters, which match nothing for Intel, so "Why did Intel stop paying
     dividends?" came back "Not found".
   - Two answers were only partly right: AMD's OpenAI deal, and only one of Pfizer's IRA-selected drugs.

Earlier spot checks: the router was 97% accurate on 33 labelled questions, and a 20-question
retrieval check put the right chunk in the top 10 for 20 of 20.

## Quick start

**Prerequisites:** Docker Desktop, [Ollama](https://ollama.com), [uv](https://docs.astral.sh/uv/), ~10 GB disk.

```bash
# 1. models (local)
ollama pull qwen3:1.7b          # router, grader
ollama pull qwen3:4b-instruct   # planner, answer writer, baseline
ollama pull qwen3:8b            # eval judge (only for evals)

# 2. config
cp .env.example .env            # set SEC_USER_AGENT (your contact, required by SEC) and passwords

# 3. services + app
mkdir -p data                   # create it as your user before docker does (Linux: root-owned otherwise)
docker compose up -d            # postgres :5433, qdrant :6333, api :8000, ui :8501 (builds the image)

# 4. data (host side; pilot = 10 companies, ~30 min; --all = 50 companies, ~2 h)
uv sync
uv run python -m src.ingest.run_all            # or: --all ; resume with --from <step>
```

Open the UI at **http://localhost:8501**, or call the API:

```bash
curl -s localhost:8000/ask -H "content-type: application/json" \
     -d '{"question": "What was Intel'"'"'s R&D expense in FY2024?"}'
```

**Tracing (optional):** first add to `.env` (the api container reads them when it is created):

```
LANGFUSE_PUBLIC_KEY=pk-lf-local
LANGFUSE_SECRET_KEY=sk-lf-local
# recommended: replace the local-only defaults
LANGFUSE_INIT_USER_PASSWORD=<your password>
LANGFUSE_NEXTAUTH_SECRET=<random string>
LANGFUSE_ENCRYPTION_KEY=<64 hex chars>
LANGFUSE_MINIO_PASSWORD=<random string>
```

then `docker compose --profile tracing up -d` starts self-hosted Langfuse v3 at
http://localhost:3000 (login `admin@example.com` / your password). If you add the keys after the
stack is up, run that command again so the api picks them up. Traces store your questions and
filing excerpts on local Docker volumes.

Every `/ask` becomes one trace with a span per tool call and a generation (tokens, latency) per
LLM call. Without the keys, tracing is off.

## Models (all local)

| Role | Model |
|---|---|
| Router, grader | qwen3:1.7b (Ollama) |
| Planner, answer writer, baseline | qwen3:4b-instruct (Ollama) |
| Eval judge | qwen3:8b (Ollama) |
| Dense / sparse / reranker | bge-small-en-v1.5 / Qdrant BM25 / ms-marco-MiniLM-L-6-v2 (fastembed, ONNX) |

Chosen by measurement on a 4 GB GPU: the thinking `qwen3:4b` planner took 193 s per plan; MiniLM
reranks at 2.3 s/search vs 12.1 s for bge-reranker-base with the same 20/20 recall.

## Data

50 companies (semiconductors, banks, pharma; `config/companies.yaml`), 10-K filings FY2023–2025.
The pilot 10 (NVDA, AMD, INTC, QCOM, JPM, BAC, GS, PFE, LLY, MRK) are ingested by default;
`--all` loads all 50 (150 filings, 37,358 chunks, 712 XBRL facts). The coverage check at 50
companies reports 14 gaps: KLAC operating income; TFC, FITB and RF revenue; and REGN gross profit.
These metrics aren't tagged in the forms this mapping expects.
Numbers: XBRL companyfacts mapped to 6 canonical metrics (`config/metric_map.yaml`; R&D = total
incl. acquired IPR&D; gross profit derived where not reported). Text: 10-K Items 1, 1A, 7, 7A,
section-aware chunks ≤ 480 tokens with context headers.

## Development

See `CLAUDE.md` for every command. Tests: `uv run pytest -m "not integration"` (unit) and
`uv run pytest` (needs the services + Ollama). Build history, decisions and review findings per
phase: `docs/PHASES.md`, `docs/phase-reports/`.

## Limitations

- The eval numbers come from the 32-question quick subset; the full 120-question run (~6 h) hasn't
  been run. The questions cover the 10 pilot companies, though the index holds all 50.
- Multi-hop answers take about 2 minutes (p50 118 s) on a 4 GB GPU, which misses the PRD's 60 s target.
- No demo GIF yet.
- Intel's 10-Ks have no Item structure the parser recognises (indexed as whole documents; search works, item filters don't).
- A single local 4B model writes answers; wording can vary between runs (the verifier guards numbers and directions, not style).
- 10-K only (no 10-Q, 8-K or transcripts); US filers only.
