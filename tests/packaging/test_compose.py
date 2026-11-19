"""docker-compose.yml: parses, loopback-only ports, tracing profile, no real secrets (NFR-11)."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"
LANGFUSE = {"langfuse-web", "langfuse-worker", "langfuse-db", "langfuse-clickhouse",
            "langfuse-minio", "langfuse-redis"}

# The postgres/qdrant services as they were before Phase 6; they must stay exactly so.
POSTGRES = {
    "image": "postgres:16",
    "environment": {"POSTGRES_USER": "${POSTGRES_USER}",
                    "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
                    "POSTGRES_DB": "${POSTGRES_DB:-sec_analyst}"},
    "ports": ["127.0.0.1:${POSTGRES_PORT:-5433}:5432", "[::1]:${POSTGRES_PORT:-5433}:5432"],
    "volumes": ["pgdata:/var/lib/postgresql/data"],
    "healthcheck": {"test": ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"],
                    "interval": "5s", "timeout": "3s", "retries": 20},
}
QDRANT = {
    "image": "qdrant/qdrant:v1.12.4",
    "ports": ["127.0.0.1:6333:6333", "127.0.0.1:6334:6334", "[::1]:6333:6333",
              "[::1]:6334:6334"],
    "volumes": ["qdrant_data:/qdrant/storage"],
    "healthcheck": {
        "test": ["CMD-SHELL", "bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333 && printf \"GET /readyz "
                 "HTTP/1.0\\r\\n\\r\\n\" >&3 && grep -q \"200 OK\" <&3'"],
        "interval": "5s", "timeout": "3s", "retries": 20},
}

# Clearly-fake local-only values a secret may default to.
FAKE = re.compile(r"^(local-dev[-\w]*|pk-lf-local|sk-lf-local|0{64}|langfuse|minio|clickhouse)$")
SECRETISH = re.compile(r"PASSWORD|SECRET|SALT|ENCRYPTION_KEY|_KEY$|_AUTH$|DATABASE_URL")
VAR = re.compile(r"\$\{(\w+)(?::-([^}]*))?\}")


@pytest.fixture(scope="module")
def raw() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def rendered(tmp_path_factory) -> dict:
    """`docker compose config` with every profile, using dummy env (never the real .env)."""
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    env_file = tmp_path_factory.mktemp("env") / "dummy.env"
    env_file.write_text("POSTGRES_USER=x\nPOSTGRES_PASSWORD=y\n", encoding="utf-8")
    p = subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE), "--env-file", str(env_file),
         "--profile", "tracing", "config", "--format", "json"],
        capture_output=True, text=True, cwd=ROOT)
    if p.returncode != 0 and "unknown" in p.stderr.lower() and "compose" in p.stderr.lower():
        pytest.skip("docker compose plugin missing")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_compose_parses_with_all_services(rendered):
    assert set(rendered["services"]) == {"postgres", "qdrant", "api", "ui"} | LANGFUSE


def test_postgres_and_qdrant_unchanged(raw):
    assert raw["services"]["postgres"] == POSTGRES
    assert raw["services"]["qdrant"] == QDRANT


def test_every_published_port_is_loopback(rendered):
    published = [(name, p) for name, svc in rendered["services"].items()
                 for p in svc.get("ports", [])]
    assert published
    for name, p in published:
        assert p.get("host_ip") in ("127.0.0.1", "::1"), (name, p)


def test_langfuse_only_under_tracing_profile(raw):
    for name, svc in raw["services"].items():
        if name in LANGFUSE:
            assert svc.get("profiles") == ["tracing"], name
        else:
            assert "profiles" not in svc, name   # plain `docker compose up -d` starts these


def _secret_values(raw: dict):
    for name, svc in raw["services"].items():
        for key, value in (svc.get("environment") or {}).items():
            if SECRETISH.search(key):
                yield name, key, str(value)
        cmd = svc.get("command")
        if isinstance(cmd, list) and "--requirepass" in cmd:
            yield name, "requirepass", cmd[cmd.index("--requirepass") + 1]


def test_no_literal_secrets_only_fake_placeholders(raw):
    seen = 0
    for name, key, value in _secret_values(raw):
        seen += 1
        if key == "DATABASE_URL":   # postgresql://user:<password>@host/db
            value = re.match(r"^postgres(?:ql)?://[^:]+:(.+)@", value).group(1)
        if key.endswith("ACCESS_KEY_ID"):   # a user name, not a secret
            continue
        m = VAR.fullmatch(value)
        if m:
            default = m.group(2)
            assert default is None or default == "" or FAKE.match(default), (name, key)
        else:
            assert FAKE.match(value), (name, key, "literal secret")
    assert seen > 10


def test_user_postgres_password_comes_from_env(raw):
    assert raw["services"]["postgres"]["environment"]["POSTGRES_PASSWORD"] == \
        "${POSTGRES_PASSWORD}"


def test_api_env_overrides(raw):
    api = raw["services"]["api"]
    env = api["environment"]
    assert env["DB_HOST"] == "postgres" and str(env["DB_PORT"]) == "5432"
    assert env["QDRANT_URL"] == "http://qdrant:6333"
    assert env["OLLAMA_HOST"] == "http://host.docker.internal:11434"
    assert env["MODEL_CACHE_DIR"] == "/app/data/models"
    assert env["LANGFUSE_HOST"] == "http://langfuse-web:3000"
    assert env["LANGFUSE_PUBLIC_KEY"] == "${LANGFUSE_PUBLIC_KEY:-}"
    assert env["LANGFUSE_SECRET_KEY"] == "${LANGFUSE_SECRET_KEY:-}"
    assert "host.docker.internal:host-gateway" in api["extra_hosts"]
    assert "./data:/app/data" in api["volumes"]
    assert api["depends_on"]["postgres"]["condition"] == "service_healthy"
    assert api["depends_on"]["qdrant"]["condition"] == "service_healthy"
    assert "/health" in " ".join(api["healthcheck"]["test"])
    assert api["env_file"] == [{"path": ".env", "required": False}]


def test_ui_env_overrides(raw):
    ui = raw["services"]["ui"]
    assert ui["environment"]["API_URL"] == "http://api:8000"
    assert ui["image"] == raw["services"]["api"]["image"]
    assert ui["command"][:3] == ["streamlit", "run", "ui/app.py"]
    assert "0.0.0.0" in ui["command"] and "8501" in ui["command"]
    assert "api" in ui["depends_on"]
