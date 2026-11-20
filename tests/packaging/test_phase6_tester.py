"""Phase 6 tester: settings db override, run_all CLI exit codes, compose profile split,
Dockerfile, and README commands vs the real CLIs. No SEC, DB or real ingest."""

import importlib
import re
import runpy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from psycopg.conninfo import conninfo_to_dict

from config.settings import Settings
from src.ingest import run_all

ROOT = Path(__file__).resolve().parents[2]
README = (ROOT / "README.md").read_text(encoding="utf-8")
CLAUDE = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

OWNER = "postgresql://owner:change-me@localhost:5433/sec_analyst"
READER = "postgresql://agent_reader:change-me@localhost:5433/sec_analyst"


def _settings(**kw) -> Settings:
    return Settings(_env_file=None, sec_user_agent="t t@example.com",
                    database_url=OWNER, agent_database_url=READER, **kw)


# ---- settings ---------------------------------------------------------------------------

def test_db_host_override_rewrites_both_urls_and_keeps_credentials():
    s = _settings(db_host="postgres", db_port=5432)
    for url, user, pw in ((s.database_url, "owner", "change-me"),
                          (s.agent_database_url, "agent_reader", "change-me")):
        d = conninfo_to_dict(url)
        assert (d["host"], d["port"], d["user"], d["password"], d["dbname"]) == \
            ("postgres", "5432", user, pw, "sec_analyst")


def test_db_host_only_keeps_port():
    s = _settings(db_host="postgres")
    d = conninfo_to_dict(s.agent_database_url)
    assert (d["host"], d["port"]) == ("postgres", "5433")


def test_no_override_leaves_urls_untouched():
    s = _settings()
    assert (s.database_url, s.agent_database_url) == (OWNER, READER)


def test_tracing_enabled_needs_both_keys():
    assert not _settings().tracing_enabled
    assert not _settings(langfuse_public_key="pk").tracing_enabled
    assert _settings(langfuse_public_key="pk", langfuse_secret_key="sk").tracing_enabled


# ---- run_all ----------------------------------------------------------------------------

def _run_cli(monkeypatch, argv, fail=None):
    """Run run_all as `python -m` would (its __main__ block) with every step stubbed."""
    ran = []
    real = importlib.import_module
    stub_modules = {m for _, m, _, _ in run_all.STEPS}

    def fake_import(name, *a, **k):
        if name in stub_modules:
            step = next(s[0] for s in run_all.STEPS if s[1] == name)

            def fn(*args):
                ran.append(step)
                if step == fail:
                    raise RuntimeError(f"{step} broke")
                return 0
            return type("M", (), {"main": staticmethod(fn), "setup": staticmethod(fn)})
        return real(name, *a, **k)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    monkeypatch.setattr(sys, "argv", ["run_all", *argv])
    with pytest.raises(SystemExit) as e:
        runpy.run_module("src.ingest.run_all", run_name="__main__")
    return e.value.code, ran


def test_cli_success_exits_0(monkeypatch, capsys):
    code, ran = _run_cli(monkeypatch, [])
    assert code == 0 and ran == run_all.STEP_NAMES


def test_cli_failure_exits_1_and_stops(monkeypatch, capsys):
    code, ran = _run_cli(monkeypatch, ["--all"], fail="chunks")
    assert code == 1
    assert ran == ["db", "xbrl", "coverage", "filings", "sections", "chunks"]
    err = capsys.readouterr().err
    assert "run_all --all --from chunks" in err


def test_cli_from_skips_earlier_steps(monkeypatch, capsys):
    code, ran = _run_cli(monkeypatch, ["--from", "index"])
    assert code == 0 and ran == ["index"]


def test_from_last_step_summary_has_no_not_run(monkeypatch, capsys):
    _run_cli(monkeypatch, ["--from", "index"])
    assert "not run" not in capsys.readouterr().out


# ---- compose / Dockerfile ---------------------------------------------------------------

def test_default_compose_has_only_app_and_data_services(tmp_path):
    if not shutil.which("docker"):
        pytest.skip("docker not installed")
    env = tmp_path / "dummy.env"
    env.write_text("POSTGRES_USER=x\nPOSTGRES_PASSWORD=y\n", encoding="utf-8")
    p = subprocess.run(["docker", "compose", "-f", str(ROOT / "docker-compose.yml"),
                        "--env-file", str(env), "config", "--services"],
                       capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0, p.stderr
    assert set(p.stdout.split()) == {"postgres", "qdrant", "api", "ui"}


def test_dockerfile_user_switch_precedes_cmd_and_sync_is_frozen():
    lines = [ln.strip() for ln in (ROOT / "Dockerfile").read_text().splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    user = [i for i, ln in enumerate(lines) if ln.startswith("USER ")]
    cmd = [i for i, ln in enumerate(lines) if ln.startswith("CMD ")]
    assert user and cmd and user[-1] < cmd[-1]
    assert lines[user[-1]].split()[1] not in ("root", "0")
    syncs = [ln for ln in lines if "uv sync" in ln]
    assert syncs and all("--frozen" in ln for ln in syncs)


def test_dockerignore_excludes_env_and_data():
    ign = (ROOT / ".dockerignore").read_text().split()
    assert ".env" in ign and "data" in ign


# ---- README / CLAUDE.md commands match the real CLIs ------------------------------------

CMD = re.compile(r"uv run python -m ([\w.]+)((?:[ \t]+[^\s`#;)]+)*)")


def _commands(text: str) -> list[tuple[str, list[str]]]:
    out = []
    for m in CMD.finditer(text):
        flags = [f.split("=")[0] for f in m.group(2).split() if f.startswith("--")]
        out.append((m.group(1), flags))
    return out


@pytest.mark.parametrize("doc", ["README", "CLAUDE"])
def test_documented_modules_exist_and_flags_are_accepted(doc):
    text = README if doc == "README" else CLAUDE
    cmds = _commands(text)
    assert cmds, "no commands found"
    for module, flags in cmds:
        path = ROOT / (module.replace(".", "/") + ".py")
        assert path.exists() or (ROOT / module.replace(".", "/") / "__main__.py").exists(), \
            module
        src = path.read_text(encoding="utf-8")
        for f in flags:
            assert re.search(rf"['\"]{re.escape(f)}['\"]", src), f"{module} has no {f}"


def test_readme_run_all_help_lists_documented_flags():
    p = subprocess.run([sys.executable, "-m", "src.ingest.run_all", "--help"], cwd=ROOT,
                       capture_output=True, text=True)
    assert p.returncode == 0
    for f in ("--all", "--from"):
        assert f in p.stdout and f in README


def test_readme_run_eval_flags_parse():
    from evals import run_eval
    a = run_eval.parse_args(["--run-id", "pilot-v1", "--per-type", "quick", "--skip-noheader"])
    assert a.run_id == "pilot-v1" and a.skip_noheader


def test_readme_uvicorn_and_streamlit_targets_exist():
    assert "src.api.main:app" in README + CLAUDE
    from src.api.main import app
    paths = set(app.openapi()["paths"])
    assert {"/ask", "/ask/stream", "/health"} <= paths
    assert (ROOT / "ui" / "app.py").exists()


def test_step_returning_nonzero_is_a_failure(monkeypatch, capsys):
    """A step's main() returning 1 (e.g. a filing failed to parse) must fail the run;
    only coverage's rc=1 (gaps) is tolerated."""
    def resolve(module, func):
        name = next(s[0] for s in run_all.STEPS if s[1] == module)
        return lambda *a: 1 if name == "sections" else 0

    monkeypatch.setattr(run_all, "_resolve", resolve)
    assert run_all.main() == 1
    assert "--from sections" in capsys.readouterr().err


def test_db_host_only_with_portless_url_has_no_bogus_port():
    s = Settings(_env_file=None, sec_user_agent="t t@example.com",
                 database_url="postgresql://o:change-me@localhost/sec_analyst",
                 agent_database_url="postgresql://r:change-me@localhost/sec_analyst", db_host="postgres")
    for url in (s.database_url, s.agent_database_url):
        d = conninfo_to_dict(url)
        assert d["host"] == "postgres" and d.get("port") in (None, "")
