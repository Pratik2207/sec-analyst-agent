# Phase 1 report: Walking skeleton + financial facts

Date: 2026-11-19 · Range: `phase-1-start..phase-1-done`

## What was built
- **Project:** uv project (Python 3.12), `CLAUDE.md` with exact commands, folder layout from PRD §9.
- **Services:** `docker-compose.yml` with Postgres 16 on `localhost:5433` and Qdrant 1.12.4. Both are bound to loopback only (`127.0.0.1` and `[::1]`).
- **Database:** `sql/schema.sql` (idempotent). `src/db.py setup` applies the schema, loads `metric_map`, and creates the read-only `agent_reader` role (password from `.env`, SELECT only, read-only by default, 5 s statement timeout).
- **Config:**
  - `config/companies.yaml` lists all 50 companies (10 pilot): NVDA, AMD, INTC, QCOM, JPM, BAC, GS, PFE, LLY, MRK.
  - `config/metric_map.yaml` has ordered tag fallbacks, derived gross profit, and per-sector metric lists.
- **SEC client** (`src/sec_client.py`): User-Agent from `SEC_USER_AGENT`, at most 10 requests per second, file cache under `data/raw/`.
- **XBRL loader** (`src/ingest/download_xbrl.py`):
  - The fiscal year comes from each original 10-K, and `period_end` is stored separately.
  - Values are taken only from the same filing and period, so comparatives, 10-Qs and 10-K/As are excluded.
  - Loads are upserts.
- **Coverage check** (`src/ingest/coverage.py`): reports 0 gaps for the pilot set.
- **`sql_query` tool** (`src/tools/sql_tool.py`): a sqlglot guard (one SELECT, no data-modifying nodes), a read-only session, and the `agent_reader` role. Rows from `financial_facts` must include `accession_no`. The tool description is built from config.
- **`POST /ask` skeleton** (`src/api/main.py`): qwen3:1.7b turns the question into {ticker, metric, fiscal_year} as structured output, a parameterized SQL template fetches the value, and the answer comes back with a citation (ticker, 10-K, FY, accession number, EDGAR URL).

Loaded data: 10 companies and 144 facts. Spot checks match the published 10-K numbers: NVDA FY2025 revenue $130.50B with period end 2025-01-26, INTC FY2024 R&D $16.55B, AMD FY2024 revenue $25.79B, LLY FY2024 revenue $45.04B.

## Tests
- 124 passed, 0 failed (91 unit, 33 integration). `ruff check .` is clean.
- The phase-tester added 83 tests, covering the XBRL edge cases, 17 more SQL-guard bypass attempts, `/ask` with stubbed and live dependencies, the role and timeout behavior, and both CLIs.

| Req / criterion | Status | Evidence |
|---|---|---|
| FR-2 | MET | six metrics loaded per sector list; idempotent reload test |
| FR-3 | MET | fallback-order and canonical-mapping tests; no duplicate tags |
| FR-8 | MET | guard tests; writes refused by the role even in autocommit READ WRITE; accession_no rule |
| NFR-6 | MET | `tests/test_policy.py` (no hosted LLM clients, no `*_API_KEY` under `src/`) |
| NFR-9 | MET | `pg_sleep(6)` times out; the timeout can't be disabled from inside a SELECT |
| NFR-10 | MET | `.env` untracked and ignored; secret-pattern scan of tracked files |
| X-1 | MET | `coverage` CLI reports 0 gaps |
| X-2 | MET (after fix) | the coverage check and the tool description both read the sector lists from config |
| X-3 | MET | NVDA FY2025 has period_end 2025-01-26; QCOM's September year end is correct |
| AC1 | MET | compose healthy; DBeaver connection confirmed by the user |
| AC2–AC7 | MET | see the tests above |

## Reviews
- **Code review:** APPROVE, with no critical or high findings.
- **Security review:** no confirmed issues.

**Fixed in this phase:**
- The tool description is now built from config. The X-2 gap was reported by both the tester and the code reviewer.
- Negative amounts now print as `-$18.76 billion` instead of `$-18.76 billion`.
- Postgres and Qdrant ports are bound to loopback only. The security reviewer flagged that they were published on all interfaces, and Qdrant has no API key. IPv6 `[::1]` is bound too, because `localhost` on Windows otherwise waited 20 s per connection.
- The FR-8 "the role itself refuses writes" gap from code review was closed by the tester's autocommit test.

## Open medium/low items (not fixed; your call)
1. **(medium) A DB outage looks like "not found".** If Postgres is down or a password is wrong, `/ask` returns 200 with "Not found in the filings." instead of a 503 (`src/api/main.py`). This is worth fixing when Phase 3/4 rework `/ask`.
2. **(low) Mixed R&D definitions.** `ResearchAndDevelopmentExpense` is tried first, so MRK's figure includes acquired IPR&D (FY2023: $30.5B), while PFE and LLY fall back to the excluding-IPR&D tag. This is a data-definition decision: prefer one definition, or document it.
3. **(low) The `accession_no` rule is checked after the query runs, by column name only.** An alias like `ticker AS accession_no` passes it. It's a citation rule, not a security control. It also rejects aggregates over `financial_facts`, which is fine because the PRD wants math in `calculate`.
4. **(low) `pyproject` declares `ollama>=0.4`, but `think=False` needs ≥0.5.** The lockfile pins 0.6.3.
5. **(hardening)** `ensure_reader_role` should refuse when the reader user equals the owner or is a superuser. Return a generic DB error from the API and log the details. Add `.env.*` / `!.env.example` to the repo's `.gitignore`.
6. Qdrant has no compose healthcheck yet. Phase 2 can add one.

## Deviations from the plan
- **Reviews ran alongside the tester.** The first tester run was lost when the session ended, so the code and security reviews ran in parallel with the second run. The reviewers are read-only, and the tester only adds tests.
- **`.env` / `.env.example` were created by the user.** A permission deny rule blocks Claude from writing them, and a privacy guard keeps the email out of commands. The template content was provided.
- **The DB passwords were changed after the container was first created.** The owner password was synced with `ALTER ROLE`, and the reader password through `src.db setup`.
- **BNY Mellon's ticker is `BNY`** (formerly `BK`).
- **Gross profit for pharma (and QCOM)** is derived as revenue minus cost of revenue, because no `GrossProfit` tag is reported. The `xbrl_tag` is stored as `derived:<a>-<b>` for traceability.
- **DBeaver needed `Asia/Kolkata` as its client time zone.** Java's legacy `Asia/Calcutta` is rejected by the Postgres 16 image. This is user-side only.
