"""End-to-end /ask against the real database (sec_analyst) and Ollama."""

import httpx
import pytest
from fastapi.testclient import TestClient

from config.settings import get_settings
from src.api.main import app

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def client():
    try:
        httpx.get(get_settings().ollama_host, timeout=3)
    except httpx.HTTPError:
        pytest.skip("Ollama not running")
    return TestClient(app)


def test_intel_rd_fy2024(client):
    r = client.post("/ask", json={"question": "What was Intel's R&D expense in FY2024?"})
    assert r.status_code == 200
    body = r.json()
    assert "Intel" in body["answer"] and "$16.55 billion" in body["answer"]
    cite = body["citations"][0]
    assert cite["ticker"] == "INTC" and cite["fiscal_year"] == 2024 and cite["form"] == "10-K"
    assert cite["url"].startswith("https://www.sec.gov/Archives/edgar/data/50863/")
    assert body["latency_ms"] > 0 and body["tokens"]["prompt"] > 0


def test_unknown_year_is_not_found(client):
    r = client.post("/ask", json={"question": "What was NVIDIA's revenue in FY2030?"})
    assert r.json()["answer"] == "Not found in the filings."
    assert r.json()["citations"] == []
