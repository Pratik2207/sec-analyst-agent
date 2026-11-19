-- SEC Filings Analyst schema (database: sec_analyst). Idempotent: safe to re-run.
-- Applied by `uv run python -m src.db setup`, or run it from DBeaver's SQL editor.
-- The read-only agent_reader role is created by `src.db setup` (its password lives in .env).

CREATE TABLE IF NOT EXISTS companies (
  ticker        TEXT PRIMARY KEY,
  cik           TEXT NOT NULL,
  name          TEXT NOT NULL,
  sector        TEXT NOT NULL,
  fy_end_month  SMALLINT          -- e.g. 1 for NVIDIA (January)
);

CREATE TABLE IF NOT EXISTS financial_facts (
  ticker        TEXT REFERENCES companies(ticker),
  fiscal_year   SMALLINT,
  period_end    DATE,
  metric        TEXT,             -- canonical: revenue, gross_profit, rd_expense, ...
  value         NUMERIC(20, 2),
  unit          TEXT,             -- USD
  xbrl_tag      TEXT,             -- original tag, or "derived:<a>-<b>", for traceability
  accession_no  TEXT,
  PRIMARY KEY (ticker, fiscal_year, metric)
);
CREATE INDEX IF NOT EXISTS financial_facts_metric_year_idx ON financial_facts (metric, fiscal_year);

CREATE TABLE IF NOT EXISTS metric_map (
  xbrl_tag  TEXT PRIMARY KEY,
  metric    TEXT NOT NULL
);
