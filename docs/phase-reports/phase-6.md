# Phase 6 report: Scale and ship

Date: 2026-11-20 · Range: `phase-6-start..phase-6-done` · Tracks: 3 (parallel worktrees, merged)

**Status: shipped. Three items are DEFERRED (user):**
- The 50-company scale-up (AC1).
- The eval re-run, the README results table and the failure analysis (AC5, X-7).
- The demo GIF. The Chrome extension wasn't connected, so it couldn't be recorded here.

All three are single commands, listed at the end.

## What was built
- **Contract (main):**
  - The `Tracer` interface (trace/span/generation) with a no-op default, hooked into `/ask`, the tool dispatcher, the fast path and every LLM call (tokens, latency, and failed calls too).
  - `graph.run_agent_events`, which yields each step as soon as its node finishes.
  - Settings for the Langfuse keys (tracing is on only when both are set), the in-Docker database host override, and the UI's API URL.
  - A startup warning when an ablation switch is active.
- **track-a, UI** (`ui/`): Streamlit chat with live steps (an `st.status` box fed by SSE), the answer with bold [n] markers, a numbered sources panel with EDGAR links, an expandable trace (steps, tokens, latency), an API health check in the sidebar, example questions, and a not-investment-advice note. It falls back to `/ask` if streaming isn't available.
- **track-b, tracing and streaming:**
  - `LangfuseTracer` (SDK 5.2, OpenTelemetry-based; observations nest through the current context). It never breaks a request; failures become a no-op.
  - `POST /ask/stream` (SSE): step events, then exactly one final or error event. The trace context is preserved across the streaming generator.
- **track-c, packaging:**
  - `Dockerfile`: one image for the API and UI, uv `--frozen`, non-root, 2.09 GB.
  - Compose: `api` and `ui` services alongside postgres/qdrant, all on loopback. **Langfuse v3** (6 containers) sits under `--profile tracing`, with headless init.
  - `src/ingest/run_all.py`: one-command, resumable ingest (`--all`, `--from STEP`) that fails on a non-zero step.
- **Main:** the README (what/why, architecture, safeguards, quick start, tracing, models, data, limitations; the results table is marked pending) and the `CLAUDE.md` commands.

## Verified live
- `docker compose up -d --build` brings up postgres, qdrant, a healthy api and the ui.
- **Containerised fast path:** "Intel's R&D FY2024" returns $16.55B with an EDGAR link. 7 s cold, sub-second warm.
- **Containerised `/ask/stream`:** steps arrived live (route at 0 s, plan at 41 s, answer at 74 s), followed by a correct, cited final answer ("JPMorgan Chase … $57.05 billion").
- **The tester's live checks:** health, UI 200, `/ask`, and `/ask/stream`, where ≥ 3 steps arrive before the final and no internal fields leak.

## Tests
- **Unit: 940 passed.** Integration: the tester's 4 live tests passed.
- **The tester added 34 tests:** SSE error cases and ordering, a server→UI round trip, tracing with no keys or a dead Langfuse host (/ask stays under 5 s), the settings override, `run_all` via `__main__`, compose and Dockerfile properties, README/CLAUDE.md commands checked against the real CLIs, and UI escaping and errors.

| Req / AC | Status | Evidence |
|---|---|---|
| AC1: 50 companies ingested | DEFERRED (user) | `uv run python -m src.ingest.run_all --all` (about 2 h) |
| AC2 / NFR-11: `compose up` + `run_all` gives a working /ask and UI | MET (stack live), run_all stub-tested | live tests; compose and Dockerfile tests |
| AC3 / FR-15 / FR-19: chat, sources, trace, live steps | MET | AppTest smoke tests; live stream shows steps before the final |
| AC4 / NFR-12: Langfuse trace per /ask | MET (offline), live server untested | the span tree checked with an in-memory exporter; the tracing profile wasn't started (memory) |
| AC5 / X-7: eval re-run, results, top 3 failures | DEFERRED (user) | Phase 5 runner; README marked pending |
| X-8: README | MET except the results table and GIF (deferred) | the commands are verified by tests |

## Reviews
- **Code review: APPROVE.** Both mediums fixed:
  - **Fresh clone on Linux:** `./data` would be created root-owned. The README now creates it first.
  - **Interrupted UI answer:** it could leave an unanswered question in the history. A placeholder answer is now stored with the question.
- **Lows fixed:**
  - no per-request Langfuse flush thread
  - failed LLM calls are traced
  - `run_all` fails on a non-zero step (`parse_sections` returns 1 when a filing fails)
  - eval runs get one trace per question
  - README: add the Langfuse keys before starting the profile
  - the UI waits for a healthy API
- **Lows kept:**
  - The private OpenTelemetry start-time adjustment is kept; it's guarded.
  - `@app.on_event` is deprecated but works; switch to the lifespan handler later.
  - The SSE `token` event type from the original plan isn't implemented, because FR-19 only needs steps.
- **Security review: no confirmed issues.** Fixed:
  - Markdown links and images are stripped from answers before display, since filing-influenced text shouldn't make the browser fetch URLs.
  - The README asks you to override the Langfuse default credentials.
  - A `DB_HOST` without `DB_PORT` no longer produces port "None".
- **Security notes deferred:**
  - Pass only the needed variables to the containers instead of all of `.env`; the Settings model currently requires the owner URL.
  - Mount `./data` read-only for sections.
  - Pin images by digest.
  - Limit concurrent streams if the API is ever exposed beyond loopback.
- **Tester failure, fixed:** an order-dependent test failure. Without its own tracer provider, the Langfuse SDK installed itself as OpenTelemetry's process-global provider. The client now gets a dedicated provider, which also avoids taking over other OpenTelemetry use.

## Left for you
1. **Scale to 50 companies** (about 2 h, resumable): `uv run python -m src.ingest.run_all --all`
2. **Evals** (quick, about 1.5 h; full, about 6 h): `uv run python -m evals.run_eval --run-id pilot-v1 --per-type quick --skip-noheader`. Then the README gets the results table and the top 3 failure causes.
3. **Approve the dataset** (`evals/dataset_review.md`).
4. **Demo GIF:** record http://localhost:8501, or reconnect the Claude Chrome extension and ask Claude to record it.
5. **Optional tracing:** add the Langfuse keys to `.env`, then `docker compose --profile tracing up -d`.

## Deviations from the plan
- **Explicit trace spans and generations** through a Tracer interface instead of a LangChain callback handler, because the agent calls Ollama directly.
- **Langfuse runs under a Compose profile,** for memory.
- **Langfuse SDK 5.2:** it needs a v3+ server, which is what the Compose file uses.
- **Deferred by you:** the 50-company run, the evals and the GIF.
