"""Runtime settings, read from environment variables and `.env`."""

from functools import lru_cache
from pathlib import Path

import yaml
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
