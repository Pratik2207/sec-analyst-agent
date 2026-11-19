# Phase 2 report: Text pipeline

Date: 2026-11-19 · Range: `phase-2-start..phase-2-done` · Tracks: 2 (parallel worktrees, merged)

## What was built
- **Contract** (`src/ingest/chunk_schema.py`, `src/retrieval/types.py`): the Chunk record, `[Company | 10-K | FYxxxx | Item … | Section]` headers, deterministic `point_id`, a bge-tokenizer `count_tokens`, `SearchFilters`/`SearchHit`, and the `hybrid_search` signature (with the ablation flags Phase 5 needs).
- **track-a** (download, parse, chunk):
  - `download_filings.py`: picks filings from `financial_facts` accession numbers, so text and numbers share FY and period. Looks up the primary document in SEC submissions, including older pages for heavy filers like JPM. Cache plus manifest.
  - `parse_sections.py`: flattens the HTML and finds Items, skipping the table of contents. Resolves bank-style Item 7 cross-references to the real MD&A, splits by subheading with one section per risk, and turns small tables into Markdown. Falls back to the logged whole document.
  - `chunker.py`: chunks of ≤ 480 tokens, header included, with about 15% overlap at paragraph and then sentence boundaries. Tables are their own chunks.
- **track-b** (indexing and search):
  - `index_qdrant.py`: dense (bge-small, 384, cosine) plus BM25 sparse (IDF) vectors, with payload indexes on ticker, sector, item, accession_no and fiscal_year. Each filing is replaced on re-index (delete by accession, then upsert).
  - `hybrid_search.py`: Qdrant Query API with two prefetches, RRF fusion, then reranking of the top 30 down to k. The bge query instruction goes on the dense query only.
  - `reranker.py`: fastembed cross-encoder.
- **Main session:**
  - Qdrant compose healthcheck (AC0).
  - `scripts/retrieval_check.py` and `evals/retrieval_check.jsonl` (20 questions across all 10 companies, 3 of them unfiltered).
  - Stale-point deletion; qdrant-client pinned to 1.12 to match the server.

**Data:** 30/30 pilot filings, 8,099 chunks, and 8,099 points in Qdrant `filings`. 27 filings were parsed into Items. Intel's FY2023–25 10-Ks use the logged `full` fallback.

## Retrieval check (AC6) and reranker choice
| Config | Recall@10 | Rank 1 | Latency/search (CPU) |
|---|---|---|---|
| bge-reranker-base, pool 30 | 20/20 | 17 | 12.1 s |
| bge-reranker-base, pool 15 | 20/20 | n/a | 6.1 s |
| **MiniLM-L6, pool 30 (default, user's choice)** | **20/20** | 16 | **2.3 s** |
| No reranker | 20/20 | 13 | 0.02 s |

After the LLY re-parse, the default config was re-run: 20/20, p50 2.36 s.

## Tests
- **255 passed, 0 failed.** `ruff check .` is clean.
- The phase-tester added 57 tests:
  - real-data invariants over all 8,099 chunks and the manifest
  - the cross-reference resolver and fallback logging
  - a real-Qdrant `test_` collection: schema, idempotency, stale points, filters
  - read-only checks on `filings`
- After the fixes, the full suite (which includes all of the tester's tests) was re-run instead of launching the tester again.

| Req / AC | Status | Evidence |
|---|---|---|
| AC0 Qdrant healthy | MET | compose healthcheck on /readyz; `docker compose ps` shows (healthy) |
| AC1 / FR-1 | MET | 30/30 filings; re-run makes 0 network calls; manifest matches `financial_facts` |
| AC2 / FR-4 | MET (after fix) | Items or logged fallback for every filing; risk-per-section for all 27 non-fallback filings (LLY fixed) |
| AC3 / FR-5 | MET | every chunk ≤ 480 tokens; header, payload and keys checked; ~15% overlap; MD&A tables as Markdown |
| AC4 / NFR-8 | MET (after fix) | idempotent re-index; stale points removed, including the empty-file case |
| AC5 / FR-6 | MET | RRF query shape; rerank 30 → 8; 7 real filter cases on `filings` |
| AC6 | MET | 20/20 in the top 10 (pass: ≥ 16) |
| X-4 | MET | fallback logged as a WARNING with the accession number; chunked as `full` |

## Reviews
- **Code review:** APPROVE, no critical or high findings.
- **Security review:** no confirmed issues.

**Fixed in this phase:**
- **LLY bold-bullet risk titles weren't headings (tester).** LLY's 1A went from 5 sections to 14/14/16. A look-ahead keeps bold bullet *lists* as body text. The other 27 filings' chunks are byte-identical.
- **An empty chunk file left stale points (tester).** The file name (the accession number) is now always cleared.
- **Stale points on re-chunk (track-b).** A filing is now deleted before it is upserted.
- **Client/server version mismatch (track-b).** qdrant-client is pinned to the 1.12 series.
- **Test adjustment.** The tester's risk-section floor was lowered from 15 to 12, because LLY FY2023/24 list exactly 14 risks (verified against the HTML).

## Open medium/low items (not fixed; your call)
1. **(medium, recommend fixing before the 50-company run) `chunker.split_text` can loop forever and grow memory without limit.** It happens when a single whitespace-free "word" exceeds the budget, such as an underscore signature line or a dot leader. The reviewer reproduced it. No pilot filing triggers it. Fix: hard-split oversized words and guard against passes that make no progress.
2. **(low) Re-index isn't atomic.** It deletes and then upserts, so a crash mid-filing leaves that filing partly indexed until the next run.
3. **(low) The furniture rule can drop short headings repeated 10 or more times** (for example "Fiscal # Compared to Fiscal #").
4. **(low) The MD&A cross-reference resolver only searches forward from the Item 7 stub.**
5. **(low) `build_filter` only treats `list` as "any of".** A tuple or set would fail at runtime.
6. **(low) Intel's 3 filings are `full` fallbacks,** so `item=` filters return nothing for Intel. A parser rule for Intel's cross-reference layout would fix this.
7. **(low) 6 MRK Item 1 chunks are marked `is_table` but are word windows** of an oversized table row.
8. **Security hardening:**
   - Qdrant has no API key (loopback only).
   - Validate SEC-supplied file names (`files[*].name`, `primaryDocument`).
   - Cap response size in `SecClient`.
   - Add per-filing error handling in the parser.
   - Pin model revisions / set `HF_HUB_OFFLINE`.
   - Strip `ix:hidden` and zero-size text before indexing.
9. **For Phase 3+:** treat retrieved chunk text as untrusted data in the prompts (indirect prompt injection). Never let chunk text pick tools or SQL.

## Follow-up after user review (2026-11-19)
You asked for item 1 to be fixed and left the low-priority items to Claude. Decisions:

**Fixed:**
- **Item 1, chunker hang.** `_hard_split` cuts any whitespace-free word over the limit into character slices. `split_text` also guards against a pass that makes no progress: it drops the carry, and fails loudly if even that doesn't help. The reviewer's repro now finishes in milliseconds (`tests/ingest_text/test_chunker_long_words.py`).
- **Item 2, re-index atomicity.** A filing is fully embedded before its old points are deleted.
- **Item 5.** Tuple and set filters now become `MatchAny`.
- **Security hardening:**
  - SEC-supplied `files[*].name` and `primaryDocument` are checked against SEC's own name shapes, so they can't escape the cache folder or alter the URL. A bad name skips that filing with a warning.
  - `SecClient.get_bytes` streams the response and caps it at 100 MB.
  - The parser logs and skips a filing that fails, instead of aborting the run.

**Deferred to Phase 6 (50-company scale-up):**
- Items 3, 4 and 6 (the furniture heuristic, the backward MD&A search, Intel's layout). They only matter for new layouts, and the coverage check at scale will show which ones are needed.
- The Qdrant API key, which needs a `.env` change by you.
- Pinning model revisions and running HF offline.

**Deferred to Phase 4:** stripping hidden text. It goes with the agent's prompt-injection handling (retrieved text is treated as data).

**Skipped:** item 7, the cosmetic `is_table` flag on 6 MRK chunks.

Tests: 272 passed.

## Deviations from the plan
- **Chunks are ≤ 480 tokens, not 500–800.** bge-small and the rerankers read at most 512 tokens.
- **fastembed (ONNX) instead of sentence-transformers.** The same models, without installing PyTorch, which saves disk.
- **The default reranker is MiniLM-L6, not bge-reranker-base.** This was your choice after the measurement above.
- **qdrant-client is pinned to `<1.13`** to match the v1.12.4 server.
- **Four sample 10-Ks were pre-fetched in main for track-a.** Worktrees have no `.env`, so the builders couldn't reach SEC themselves.
- **The first retrieval comparison was killed by low system memory.** It was re-run one configuration at a time after you freed memory.
