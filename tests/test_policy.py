"""Project policies: local models only (NFR-6), no committed secrets (NFR-10)."""

import ast
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN_LLM_MODULES = {
    "anthropic", "openai", "langchain_openai", "langchain_anthropic", "google.generativeai",
    "google.genai", "cohere", "mistralai", "groq", "litellm", "together", "langchain_google_genai",
    "langchain_cohere", "langchain_mistralai", "langchain_groq",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _is_forbidden(module: str) -> bool:
    return any(module == m or module.startswith(m + ".") for m in FORBIDDEN_LLM_MODULES)


def test_no_hosted_llm_clients_imported_under_src():
    bad = [(str(p.relative_to(ROOT)), m) for p in (ROOT / "src").rglob("*.py")
           for m in _imports(p) if _is_forbidden(m)]
    assert bad == []


def test_no_api_keys_read_under_src():
    pattern = re.compile(r"[A-Z0-9_]*API_KEY")
    bad = [str(p.relative_to(ROOT)) for p in (ROOT / "src").rglob("*.py")
           if pattern.search(p.read_text(encoding="utf-8"))]
    assert bad == []


def test_dotenv_is_ignored_and_untracked():
    assert ".env" in (ROOT / ".gitignore").read_text().splitlines()
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.splitlines()
    assert ".env" not in tracked


SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    # a postgres URL whose password is not an obvious placeholder
    re.compile(r"postgres(?:ql)?://[^:\s/]+:(?!change-me|\$\{|<)[^@\s]+@"),
]


def test_no_secrets_in_tracked_files():
    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout.splitlines()
    hits = []
    for name in tracked:
        path = ROOT / name
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [(name, p.pattern) for p in SECRET_PATTERNS if p.search(text)]
    assert hits == []
