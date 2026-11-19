"""Runtime settings, read from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"

FISCAL_YEARS = (2023, 2024, 2025)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    sec_user_agent: str
    sec_max_rps: float = 10.0
    database_url: str
    agent_database_url: str
    ollama_host: str = "http://localhost:11434"
    fast_model: str = "qwen3:1.7b"

    # Text pipeline (Phase 2). Models run via fastembed (ONNX, CPU), cached under data/models.
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "filings"
    embed_model: str = "BAAI/bge-small-en-v1.5"
    embed_dim: int = 384
    sparse_model: str = "Qdrant/bm25"
    # MiniLM-L6: 20/20 recall@10 and 16/20 at rank 1 on the retrieval check at 2.3 s/search
    # on CPU, vs bge-reranker-base 17/20 at 12.1 s (Phase 2 measurement, user's choice).
    rerank_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    # bge-small and bge-reranker-base read at most 512 tokens; keep whole chunks inside that.
    chunk_max_tokens: int = 480
    chunk_min_tokens: int = 300
    chunk_overlap: float = 0.15
    model_cache_dir: Path = DATA_DIR / "models"

    # Phase 3: answer writer (also used by the naive RAG baseline). The plain "qwen3:4b" tag
    # is the thinking-only 2507 build (ignores think=False: ~280 tokens of reasoning even for
    # one sentence); the same-size instruct build answers directly.
    answer_model: str = "qwen3:4b-instruct"
    baseline_k: int = 8

    # Phase 4: planner (whole plan in one structured-output call). PRD 5.1 wants thinking on
    # for the planner; the thinking build ("qwen3:4b") is much slower on this GPU, so the
    # default is decided by measurement in Phase 4 (see the phase report).
    planner_model: str = "qwen3:4b-instruct"
    planner_think: bool = False
    grader_model: str = "qwen3:1.7b"
    llm_num_ctx: int = 8192   # agent LLM calls (Ollama default 4096 is too small for evidence)
    # Per agent LLM call; a model swap on the 4 GB GPU can take ~60 s, the slowest observed
    # answer ~270 s. A stalled Ollama becomes LLMError instead of hanging /ask forever.
    llm_timeout_s: float = 300.0

    # Phase 5 ablation switches (defaults = the full system).
    search_use_reranker: bool = True      # search_filings tool
    search_use_sparse: bool = True        # search_filings tool
    agent_disabled_tools: list[str] = []  # e.g. ["sql_query"] for the "text only" ablation

    # Phase 6: tracing (NFR-12) is on only when both keys are set (Langfuse project keys).
    langfuse_host: str = "http://localhost:3000"
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Phase 6: inside docker the database is "postgres:5432", not "localhost:5433"; these
    # rewrite the host/port of DATABASE_URL and AGENT_DATABASE_URL without touching .env.
    db_host: str | None = None
    db_port: int | None = None
    # Streamlit UI -> API
    api_url: str = "http://localhost:8000"

    @model_validator(mode="after")
    def _apply_db_override(self) -> "Settings":
        if self.db_host or self.db_port:
            from psycopg.conninfo import conninfo_to_dict, make_conninfo

            def swap(url: str) -> str:
                d = conninfo_to_dict(url)
                d["host"] = self.db_host or d.get("host")
                d["port"] = str(self.db_port or d.get("port"))
                return make_conninfo(**d)

            self.database_url = swap(self.database_url)
            self.agent_database_url = swap(self.agent_database_url)
        return self

    @property
    def tracing_enabled(self) -> bool:
        return bool(self.langfuse_public_key and self.langfuse_secret_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml(name: str) -> dict:
    with open(CONFIG_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_companies(pilot_only: bool = False) -> list[dict]:
    companies = load_yaml("companies.yaml")["companies"]
    return [c for c in companies if c.get("pilot")] if pilot_only else companies


def load_metric_map() -> dict:
    return load_yaml("metric_map.yaml")
