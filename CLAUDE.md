# SEC Filings Analyst Agent

Local AI analyst over SEC 10-K filings. PRD: `docs/PRD.md`. Phase plan: `docs/PHASES.md`.

## Commands (run from the repo root)
- Install: `uv sync`
- Services only: `docker compose up -d postgres qdrant` (Postgres localhost:5433, Qdrant 6333)
- Full app: `docker compose up -d` (adds api :8000 and ui :8501); with tracing:
  `docker compose --profile tracing up -d` (Langfuse v3 at :3000)
- One-command ingest: `uv run python -m src.ingest.run_all [--all] [--from STEP]`
- DB setup (schema + metric_map + read-only role, idempotent): `uv run python -m src.db setup`
- Load XBRL facts (pilot 10; `--all` for 50): `uv run python -m src.ingest.download_xbrl`
- Coverage check: `uv run python -m src.ingest.coverage`
- API: `uv run uvicorn src.api.main:app --port 8000` (POST /ask, POST /ask/stream SSE)
- UI: `uv run streamlit run ui/app.py`
- Evals: `uv run python -m evals.run_eval --run-id ID [--per-type quick] [--skip-noheader]`
  (resumable; report in evals/results/ID/report.md); dataset check:
  `uv run python -m evals.validate_dataset`
- Unit tests: `uv run pytest -m "not integration"`
- All tests (needs docker postgres + Ollama): `uv run pytest`
- Lint: `uv run ruff check .`

## Rules
- Runtime uses local models only (Ollama + Hugging Face). Never import hosted LLM clients
  under `src/`; `tests/test_policy.py` enforces this.
- Secrets live only in `.env` (gitignored). `.env.example` holds placeholders.
- Ingestion uses `DATABASE_URL` (owner). The agent's `sql_query` tool uses only
  `AGENT_DATABASE_URL` (the read-only `agent_reader` role, 5 s statement timeout).
- All SEC requests go through `src/sec_client.py` (User-Agent from `SEC_USER_AGENT`, <= 10 req/s,
  cached under `data/raw/`).
- Models are set in `.env` (`FAST_MODEL`, ...), never hard-coded.
- Run Python with `uv run`; imports are rooted at the repo (`from src...`, `from config...`).
