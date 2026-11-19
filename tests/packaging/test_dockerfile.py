"""Dockerfile / .dockerignore checks (NFR-10, NFR-11)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = (ROOT / "Dockerfile").read_text(encoding="utf-8")
LINES = [ln.strip() for ln in DOCKERFILE.splitlines() if ln.strip() and not ln.startswith("#")]


def test_runs_as_non_root_user():
    users = [ln.split()[1] for ln in LINES if ln.startswith("USER ")]
    assert users and users[-1] not in ("root", "0")


def test_dependencies_installed_frozen_without_dev():
    sync = [ln for ln in LINES if "uv sync" in ln]
    assert sync and all("--frozen" in ln and "--no-dev" in ln for ln in sync)


def test_uv_image_is_pinned():
    uv = [ln for ln in LINES if "astral-sh/uv" in ln]
    assert uv and all(":latest" not in ln and "uv:" in ln for ln in uv)


def test_no_env_file_copied():
    copies = [ln for ln in LINES if ln.startswith(("COPY", "ADD"))]
    assert not any(".env" in ln or ln.split()[1] == "." for ln in copies), copies
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", ".venv", "data", ".git", ".claude", "evals/results"):
        assert entry in ignored


def test_api_default_cmd_and_ports():
    assert any(ln.startswith("CMD") and "uvicorn" in ln and "0.0.0.0" in ln for ln in LINES)
    expose = " ".join(ln for ln in LINES if ln.startswith("EXPOSE"))
    assert "8000" in expose and "8501" in expose
