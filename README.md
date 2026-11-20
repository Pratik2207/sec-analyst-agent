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

> **Evaluation pending.** The eval harness (120 hand-checked questions, agent vs naive RAG,
> 4 ablations, NFR PASS/FAIL table) is built and tested; the run itself takes ~1.5 h (quick,
> 32 questions) to ~6 h (full) on a 4 GB GPU and has not been run yet. To produce the table:
>
> ```
> uv run python -m evals.run_eval --run-id pilot-v1 --per-type quick --skip-noheader
> ```
> The report lands in `evals/results/pilot-v1/report.md`; its headline table and the top 3
> failure causes go here.

Measured so far (pilot data, this machine — GTX 1650 4 GB):

| | |
|---|---|
| Fast path (single number) | ~0.6 s warm, p50 3.6 s incl. routing on the eval sample |
| Multi-hop (semis question) | correct ("none"), 8 citations, 42–107 s, 3 tool calls |
| Router accuracy (33 labelled questions) | 97% |
| Retrieval check (20 questions) | 20/20 right chunk in the top 10 |

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
The pilot 10 (NVDA, AMD, INTC, QCOM, JPM, BAC, GS, PFE, LLY, MRK) are ingested by default.
Numbers: XBRL companyfacts mapped to 6 canonical metrics (`config/metric_map.yaml`; R&D = total
incl. acquired IPR&D; gross profit derived where not reported). Text: 10-K Items 1, 1A, 7, 7A,
section-aware chunks ≤ 480 tokens with context headers.

## Development

See `CLAUDE.md` for every command. Tests: `uv run pytest -m "not integration"` (unit) and
`uv run pytest` (needs the services + Ollama). Build history, decisions and review findings per
phase: `docs/PHASES.md`, `docs/phase-reports/`.

## Limitations

- Pilot-scale numbers above; the 50-company run and the eval table are pending (commands above).
- Intel's 10-Ks have no Item structure the parser recognises (indexed as whole documents; search works, item filters don't).
- A single local 4B model writes answers; wording can vary between runs (the verifier guards numbers and directions, not style).
- 10-K only (no 10-Q, 8-K or transcripts); US filers only.
