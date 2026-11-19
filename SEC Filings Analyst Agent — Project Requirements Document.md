# SEC Filings Analyst Agent — Project Requirements Document

Nov 19, 2026 · @Pratik Sonawane

## 1. Overview

We will build an AI analyst that answers plain-English questions about 50 US public companies, using their SEC annual reports (10-K), and backs every answer with a source.

**Problem.** 10-K reports are long (100+ pages each). Comparing numbers and explanations across many companies and years takes an analyst hours. Plain RAG fails on these questions because the answer is spread across several reports and needs math.

**What the system does.**

- Answers number questions ("What was Intel's R&D spend in FY2024?") from structured financial data.
- Answers text questions ("Why did AMD's gross margin fall?") from the written sections of the reports.
- Answers multi-step questions ("Which chip companies raised R&D as a share of revenue while gross margin fell?") by planning, fetching data in steps, and calculating.
- Cites every claim: company, form, fiscal year, section, and link to the filing.
- Says "not found" instead of guessing.

**Who it is for.**  users: students and retail investors who want quick, sourced answers from filings.

**Core design choice.** Two stores, one agent. Text lives in Qdrant (vector search). Numbers live in PostgreSQL (SQL), using the Postgres install you already have and browse with DBeaver. The agent decides which to use for each step.

## 2. Scope

Version 1 covers 50 companies in 3 sectors, 10-K filings for fiscal years 2023–2025, in English, running locally.

**Data coverage (v1)**

| Sector | Companies | Examples |
| --- | --- | --- |
| Semiconductors | 17 | NVDA, AMD, INTC, QCOM, AVGO, TXN, MU |
| Banks | 17 | JPM, BAC, WFC, C, GS, MS |
| Pharma | 16 | PFE, MRK, LLY, ABBV, JNJ, BMY |

Total: about 150 filings (50 companies × 3 years). The final ticker list lives in `config/companies.yaml`.

**In scope**

- Download and parse 10-K filings and XBRL financial data from SEC EDGAR.
- Section-aware chunking and hybrid search in Qdrant.
- Financial facts tables in PostgreSQL.
- Agent loop with planning, tool routing, self-checking, and citations.
- FastAPI backend and a Streamlit chat UI with a sources panel.
- Eval harness comparing the agent against a naive RAG baseline.
- Tracing of every agent run.

**Out of scope (v1)**

- 10-Q quarterly filings, 8-Ks, earnings call transcripts (candidates for v2).
- Non-US companies and Indian filings.
- Live stock prices or market data.
- Investment advice or buy/sell recommendations.
- User accounts, multi-tenant hosting, and production auth.
- Fine-tuning any model.

## 3. Functional requirements

P0 = must have for v1. P1 = should have. P2 = nice to have.

| ID | Requirement | Priority |
| --- | --- | --- |
| FR-1 | Download 10-K filings for every company in `companies.yaml` from SEC EDGAR, with a compliant User-Agent and ≤ 10 requests/second. | P0 |
| FR-2 | Download XBRL companyfacts JSON and load key metrics (revenue, gross profit, R&D, operating income, net income, total assets) into PostgreSQL. | P0 |
| FR-3 | Map different XBRL tags for the same metric to one canonical name (e.g. `Revenues` and `RevenueFromContractWithCustomerExcludingAssessedTax` → `revenue`). | P0 |
| FR-4 | Split each 10-K into Items (1, 1A, 7, 7A, 8) and then by subheading. | P0 |
| FR-5 | Chunk text with context headers and metadata, embed, and index into Qdrant with dense + sparse vectors. | P0 |
| FR-6 | Hybrid search with metadata filters (ticker, sector, fiscal year, item) and reranking. | P0 |
| FR-7 | Agent plans a question into sub-steps and picks tools per step. | P0 |
| FR-8 | Agent runs read-only SQL against PostgreSQL for numeric questions. | P0 |
| FR-9 | Agent computes ratios and % changes with a calculator tool, never in its head. | P0 |
| FR-10 | Agent grades retrieved chunks and rewrites the query when results are weak (max 2 retries per step). | P0 |
| FR-11 | Every claim in the answer carries a citation: ticker, form, fiscal year, section, and EDGAR URL. | P0 |
| FR-12 | Agent answers "not found in the filings" when evidence is missing. | P0 |
| FR-13 | Verifier checks that each cited number appears in its source before the answer is returned. | P1 |
| FR-14 | REST endpoint `POST /ask` returns answer, citations, steps taken, tokens, and latency. | P0 |
| FR-15 | Streamlit UI shows the chat, a sources panel, and an expandable agent trace. | P1 |
| FR-16 | Naive RAG baseline with the same corpus, for comparison. | P0 |
| FR-17 | Eval runner scores both systems on the eval set and writes a results report. | P0 |
| FR-18 | Fast path: simple single-fact questions skip the full agent loop. | P1 |
| FR-19 | Streaming of agent steps to the UI. | P2 |
| FR-20 | Add 10-Q filings and quarterly questions. | P2 |

## 4. Non-functional requirements

Targets are for v1 on a single laptop. They are starting goals; adjust them after the first eval run.

| Area | Requirement | Target |
| --- | --- | --- |
| Accuracy | Correct answers on the eval set | ≥ 80% agent; beat naive RAG by ≥ 25 points on multi-hop |
| Faithfulness | Cited numbers match their source | ≥ 95% |
| Retrieval | Recall@10 on gold chunks | ≥ 85% |
| Latency | Simple question (fast path) | p50 < 5 s |
| Latency | Multi-hop question | p50 < 60 s, p95 < 120 s on an 8 GB GPU |
| Cost | API cost per question | $0 (local models only) |
| Loop safety | Max agent steps per question | 8, then return a partial answer |
| Reliability | Ingestion is re-runnable without duplicates | Idempotent upserts by chunk ID |
| Security | SQL tool access | Read-only Postgres role (SELECT only), 5 s statement timeout |
| Security | Secrets | Only in `.env`, never committed |
| Reproducibility | Full setup from a clean machine | `docker compose up` + one ingest command |
| Observability | Every run traced | Steps, tool calls, tokens, latency in Langfuse |

## 5. Tech stack

Qdrant and Langfuse run locally in Docker. PostgreSQL is your existing local install, managed in DBeaver. No external APIs: every model is open-source and runs locally through Ollama or Hugging Face. Python 3.11+ throughout.

| Layer | Choice | How it is used | Alternative |
| --- | --- | --- | --- |
| Language | Python 3.11+, `uv` for packages | All code | Poetry |
| Data source (text) | `edgartools` | Download 10-Ks, split into Items | `sec-edgar-downloader` + BeautifulSoup |
| Data source (numbers) | SEC XBRL companyfacts API (`data.sec.gov`) | Clean JSON of every reported metric | Parse tables by hand (avoid) |
| Structured store | PostgreSQL (existing install) + DBeaver as the GUI | Financial facts table; agent runs SELECT queries through psycopg 3 as a read-only role | DuckDB |
| Vector store | Qdrant (Docker) | Text chunks, dense + sparse vectors, payload filters | pgvector |
| Dense embeddings | `BAAI/bge-``base-en-v1.5 from Hugging Face, via sentence-transformers (768 dims)` | Semantic search | `BAAI/bge-small-en-v1.5 (384 dims, faster on CPU)` |
| Sparse vectors | BM25 via `fastembed` | Exact terms: tickers, metric names | SPLADE |
| Reranker | `BAAI/bge-reranker-v2-m3` from Hugging Face (CrossEncoder) | Rerank top 30 → top 8 | BAAI/bge-reranker-base (smaller, faster) |
| Agent framework | LangGraph | State machine for the agent loop | Plain Python loop with tool calling |
| LLM (planner, answer) | qwen3:8b via Ollama (local, native tool calling) | Planning, tool calls, final answer | llama3.1:8b, or a newer Qwen release of similar size |
| LLM (grader) | qwen3:4b via Ollama, thinking off | Grade chunks, cheap checks | qwen3:1.7b if memory is tight |
| API | FastAPI + Pydantic | `POST /ask`, health checks | Flask |
| UI | Streamlit | Chat, sources panel, trace view | Next.js |
| Tracing | Langfuse (self-hosted, Docker) | Trace every agent run | LangSmith, Arize Phoenix |
| Evals | Exact match for numbers + RAGAS / LLM-as-judge run on a local Ollama model | Score agent vs baseline | DeepEval |
| Testing | pytest | Unit tests for parsers, tools, chunker | — |
| Packaging | Docker Compose | Qdrant, Langfuse, app | — |

**Why two stores.** Vector search is good at meaning but bad at exact numbers and math. SQL is exact. Keeping numbers in PostgreSQL stops the LLM from reading numbers out of text chunks and getting them wrong.

### 5.1 Model policy: local and open-source only

No paid or hosted APIs are used. LLMs run in Ollama; embeddings and the reranker are Hugging Face models run in Python. Each model downloads once, then everything runs offline.

| Phase | What runs | Models allowed |
| --- | --- | --- |
| Build time (writing code, debugging, drafting eval questions) | Developer tooling | Claude subscription (Claude app / Claude Code) is fine |
| Run time (ingestion, agent reasoning, grading, evals) | The SEC Filings Analyst itself | Local open-source models only: Ollama + Hugging Face |

No Anthropic, OpenAI or other API key is ever read by the application code. A test fails if any LLM client other than Ollama is imported under src/.

| Role | Model | Download size (approx.) | Runs in |
| --- | --- | --- | --- |
| Planner, answer writer | qwen3:8b | 5 GB | Ollama |
| Grader, query rewriter, fast path | qwen3:4b | 2.5 GB | Ollama |
| Eval judge | qwen3:8b (qwen3:14b if memory allows) | 5–9 GB | Ollama |
| Dense embeddings | BAAI/bge-base-en-v1.5 | 0.4 GB | sentence-transformers |
| Sparse vectors | Qdrant/bm25 | < 0.1 GB | fastembed |
| Reranker | BAAI/bge-reranker-v2-m3 | 1.1 GB (fp16) | sentence-transformers |

**Hardware assumption:** 16 GB RAM, ideally a GPU with at least 8 GB VRAM. CPU-only works but multi-hop answers will be slow.

**Connecting:** LangGraph talks to Ollama through langchain-ollama (ChatOllama) at http://localhost:11434. Set OLLAMA\_HOST in .env.

**Making small models reliable at tool use:**

- Keep tool descriptions short and strict. Use enums for fixed values (tickers, Item numbers, metric names).
- Use Ollama structured outputs (a JSON schema in the format parameter) for the plan and the grader's verdict.
- Let plain code do what it can: resolve tickers, fill SQL templates for common metrics, do all math in the calculator tool.
- Turn thinking off for the grader and fast path to save time; keep it on for the planner.
- Detect repeated identical tool calls and stop the loop early, on top of the 8-step cap.

## 6. Architecture

The system has two halves. Offline ingestion fills two stores; at query time, one agent reads from both through its tools.

&#91;embedded content: system architecture · ingestion, two stores, agent loop\]

Ingestion flows down into the stores. Each question flows from the UI through the API to the agent, which reads the stores through its tools and returns a cited answer.

### 6.1 Ingestion pipeline

1. `download_filings.py` fetches 10-K HTML for each company and year into `data/raw/`.
2. `parse_sections.py` splits each filing into Items and subheadings, saved as JSON in `data/processed/`.
3. `chunker.py` builds chunks with context headers and metadata.
4. `index_qdrant.py` embeds chunks (dense + sparse) and upserts them into Qdrant by deterministic ID.
5. `download_xbrl.py` fetches companyfacts JSON, maps tags with `metric_map.yaml`, and loads `financial_facts` into PostgreSQL with upserts (INSERT ... ON CONFLICT DO UPDATE).
6. A coverage check reports any company, year or metric that is missing.

### 6.2 Query flow

1. The user asks a question in the Streamlit UI, which calls `POST /ask`.
2. A router sends simple single-fact questions to the fast path (one tool call + answer). Everything else goes to the agent loop.
3. The **planner** turns the question into ordered steps, e.g. "list chip companies → get R&D and revenue FY2024–2025 → compute ratios → get gross margin → filter".
4. For each step the agent calls a tool. The **grader** checks the result; if it is weak, the agent rewrites the query and retries (max 2 times per step).
5. When all steps are done, the **answer writer** drafts the answer with a citation on every claim.
6. The **verifier** checks each cited number against the tool output it came from. Failures go back to step 4 once; after that, the answer is returned with the failed claim removed and flagged.
7. The API returns answer, citations, steps, tokens and latency. Langfuse stores the full trace.

### 6.3 Agent state

The LangGraph state holds: the question, the plan (list of steps), current step index, tool results with source IDs, retry counts, and the draft answer. Hard stop at 8 tool calls.

## 7. Data design

Text is chunked by the 10-K's own structure, not by fixed token windows. Numbers skip chunking and go straight to PostgreSQL.

### 7.1 Chunking strategy

1. **Split by Item.** Keep Item 1 (Business), 1A (Risk Factors), 7 (MD&A), 7A (Market Risk). Skip Item 8 tables; XBRL covers those numbers.
2. **Split by subheading** inside each Item (e.g. MD&A → "Gross Margin", "Operating Expenses").
3. **Risk Factors: one chunk per risk** (each risk has its own bold heading).
4. **Recursive split** any piece over 800 tokens into 500–800 token chunks with \~15% overlap, breaking at paragraph then sentence boundaries.
5. **Context header** prepended to each chunk before embedding: `[NVIDIA | 10-K | FY2025 | Item 7 MD&A | Gross Margin]`.
6. **Small tables** inside MD&A (segment revenue, etc.) are converted to Markdown and kept as their own chunk with the header.

Expected size: roughly 150 filings × 150–300 chunks = 20k–45k chunks. Small enough for one local Qdrant instance.

### 7.2 Qdrant collection `filings`

- Vectors: `dense` (size per embedding model, cosine) and `sparse` (BM25).
- Point ID: deterministic hash of `accession_no + item + chunk_index`, so re-ingestion overwrites instead of duplicating.
- Payload indexes on `ticker`, `sector`, `fiscal_year`, `item`.

```json
{
  "ticker": "NVDA",
  "company": "NVIDIA",
  "sector": "semiconductors",
  "form": "10-K",
  "fiscal_year": 2025,
  "period_end": "2025-01-26",
  "item": "7",
  "section": "Gross Margin",
  "accession_no": "0001045810-25-000023",
  "source_url": "https://www.sec.gov/...",
  "chunk_index": 12,
  "text": "Gross margin decreased to ..."
}
```

### 7.3 PostgreSQL schema (database: sec\_analyst)

```sql
CREATE TABLE companies (
  ticker        TEXT PRIMARY KEY,
  cik           TEXT NOT NULL,
  name          TEXT NOT NULL,
  sector        TEXT NOT NULL,
  fy_end_month  SMALLINT          -- e.g. 1 for NVIDIA (January)
);

CREATE TABLE financial_facts (
  ticker        TEXT REFERENCES companies(ticker),
  fiscal_year   SMALLINT,
  period_end    DATE,
  metric        TEXT,             -- canonical: revenue, gross_profit, rd_expense, ...
  value         NUMERIC(20, 2),
  unit          TEXT,             -- USD
  xbrl_tag      TEXT,             -- original tag, for traceability
  accession_no  TEXT,
  PRIMARY KEY (ticker, fiscal_year, metric)
);
CREATE INDEX ON financial_facts (metric, fiscal_year);

CREATE TABLE metric_map (
  xbrl_tag  TEXT PRIMARY KEY,
  metric    TEXT NOT NULL
);

-- Read-only role used by the agent's sql_query tool
CREATE ROLE agent_reader LOGIN PASSWORD 'change-me';
GRANT CONNECT ON DATABASE sec_analyst TO agent_reader;
GRANT USAGE ON SCHEMA public TO agent_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_reader;
ALTER ROLE agent_reader SET default_transaction_read_only = on;
ALTER ROLE agent_reader SET statement_timeout = '5s';
```

The agent gets this schema in its SQL tool description, plus 3–4 example queries. Ingestion connects as the owner role; the agent connects only as agent\_reader. Keep this file as sql/schema.sql and run it once from DBeaver's SQL editor.

## 8. Agent tools

The agent has five tools. Each returns structured JSON with source IDs so the answer writer can cite them.

| Tool | Input | Output | Used for |
| --- | --- | --- | --- |
| `sql_query` | SELECT statement on PostgreSQL | Rows + `accession_no` per row | Numbers, rankings, filters across companies |
| `search_filings` | query text, filters (ticker, sector, fiscal\_year, item), k | Top reranked chunks with payload | "Why" and "what did they say" questions |
| `get_section` | ticker, fiscal\_year, item | Full Item text (truncated to a token limit) | When one chunk lacks context |
| `calculate` | Python arithmetic expression on named values | Result + the expression used | Ratios, % change, sums |
| `list_companies` | sector (optional) | Tickers, names, fiscal year end | Resolving "chip companies" to tickers |

**Tool rules**

- `sql_query` connects as the read-only agent\_reader role and rejects anything but SELECT.
- `calculate` runs in a restricted evaluator (no imports, no file or network access).
- Every tool call is logged to the trace with input, output size, and latency.
- Tool errors return a short message to the agent, which may retry once with a fix.

## 9. Folder structure

Code is split by pipeline stage: ingest, retrieval, tools, agent, serving, evals.

```text
sec-analyst-agent/
├── README.md                 # what, why, results table, demo GIF
├── docker-compose.yml        # qdrant + langfuse + app
├── pyproject.toml
├── .env.example              # OLLAMA_HOST, DATABASE_URL, SEC_USER_AGENT
├── config/
│   ├── companies.yaml        # tickers, CIKs, sectors
│   ├── metric_map.yaml       # XBRL tag -> canonical metric
│   └── settings.py
├── data/                     # gitignored
│   ├── raw/                  # downloaded filings (html)
│   ├── processed/            # parsed sections as JSON
│   └── exports/              # optional pg_dump backups
├── src/
│   ├── ingest/
│   │   ├── download_filings.py
│   │   ├── download_xbrl.py
│   │   ├── parse_sections.py
│   │   ├── chunker.py
│   │   └── index_qdrant.py
│   ├── retrieval/
│   │   ├── hybrid_search.py
│   │   └── reranker.py
│   ├── tools/
│   │   ├── sql_tool.py
│   │   ├── search_tool.py
│   │   ├── section_tool.py
│   │   ├── calculator.py
│   │   └── companies_tool.py
│   ├── agent/
│   │   ├── graph.py          # LangGraph state machine
│   │   ├── state.py
│   │   ├── planner.py
│   │   ├── grader.py
│   │   ├── answerer.py
│   │   ├── verifier.py
│   │   └── prompts/
│   ├── baseline/
│   │   └── naive_rag.py
│   └── api/
│       └── main.py           # FastAPI: POST /ask
├── ui/
│   └── app.py                # Streamlit
├── evals/
│   ├── dataset.jsonl         # questions + gold answers + gold sources
│   ├── run_eval.py
│   └── results/
└── tests/
    ├── test_chunker.py
    ├── test_sql_tool.py
    └── test_calculator.py
```

## 10. Evaluation plan

The project succeeds if the agent clearly beats naive RAG on multi-hop questions while keeping citations correct. The headline result is one table: agent vs baseline, per question type.

**Eval set: 120 questions, written by hand, each with a gold answer and gold source(s).**

| Type | Count | Example |
| --- | --- | --- |
| Single fact (number) | 40 | "What was Intel's R&D expense in FY2024?" |
| Text / explanation | 40 | "Why did AMD's gross margin change in FY2024?" |
| Multi-hop / comparison | 30 | "Which semiconductor companies raised R&D as a share of revenue while gross margin fell, FY2024 to FY2025?" |
| Unanswerable | 10 | "What was NVIDIA's revenue in FY2030?" → must say not found |

**Metrics**

| Metric | How it is measured |
| --- | --- |
| Answer correctness | Exact match (±1% tolerance) for numbers; LLM-as-judge vs gold answer for text |
| Citation accuracy | Share of citations whose source contains the claim |
| Faithfulness | RAGAS faithfulness score |
| Retrieval recall@10 | Gold chunk appears in top 10 |
| Refusal accuracy | Unanswerable questions correctly declined |
| Cost and latency | Tokens, $ and seconds per question, p50 and p95 |

**Ablations to report:** without reranker, without sparse vectors, without context headers, without SQL tool (text only). Each shows what that component adds.

**Failure analysis:** group wrong answers by cause (bad retrieval, wrong tool, math error, XBRL tag gap, fiscal year mix-up) and include the top 3 in the README.

## 11. Milestones

Start with 10 companies and scale to 50 only after the evals work.

1. **1: Data.** Download 10-Ks + XBRL for 10 companies. Build `metric_map`. Load PostgreSQL and check the tables in DBeaver. *Done when:* a SQL query returns revenue, gross profit and R&D for all 10 companies, FY2023–2025, with no gaps.
2. **2: Text pipeline.** Section parsing, chunking, Qdrant indexing, hybrid search + reranker. *Done when:* manual check of 20 questions finds the right chunk in the top 10 for at least 16.
3. **3: Agent.** Tools, LangGraph loop, citations, "not found" handling, naive RAG baseline. *Done when:* the semiconductor multi-hop question returns a correct, cited answer.
4. **4: Evals.** Write the 120-question set, build the runner, run agent vs baseline and ablations. *Done when:* results table is generated by one command.
5. **5: Scale and ship.** Scale to 50 companies, add Streamlit UI, Langfuse tracing, Docker Compose, README with results and failure analysis. *Done when:* a fresh clone runs end to end with `docker compose up` + one ingest command.

## 12. Risks and open questions

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Companies use different XBRL tags for the same metric | Missing or wrong numbers | `metric_map.yaml` with fallbacks; a coverage check that flags gaps per company |
| Fiscal years end in different months (NVIDIA: January) | Wrong year-over-year comparisons | Store `fiscal_year` and `period_end` separately; say both in answers |
| Banks report differently (no gross profit, R&D) | Cross-sector questions break | Sector-specific metric lists; agent told which metrics exist per sector |
| Section parsing fails on unusual 10-K layouts | Missing text chunks | Fall back to whole-document recursive chunking; log failures |
| Agent loops or calls tools forever | Cost and latency spikes | Hard cap of 8 steps; return partial answer with what was found |
| LLM does math in its head | Wrong ratios | Prompt forbids it; verifier recomputes numbers from tool outputs |
| SEC rate limits or blocks | Ingestion fails | User-Agent header, ≤ 10 req/s, local caching of raw files |
| Eval set too easy or biased | Inflated results | Include unanswerable and cross-sector questions; have someone else write 20 of them |

**Open questions**

- bge-base or bge-small for embeddings? Decide after a recall test on 50 questions.
- LangGraph or a hand-written loop? LangGraph is faster to build; a plain loop is easier to explain in interviews.
- Is qwen3:8b reliable enough at tool calling on your hardware, or does the planner need qwen3:14b?
- Add 10-Qs in v2, or earnings call transcripts first?
