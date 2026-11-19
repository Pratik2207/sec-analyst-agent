"""Phase 1 tester: extra unit tests for the SEC client used by the XBRL download."""

import httpx
import pytest

from config.settings import get_settings
from src import sec_client
from src.sec_client import RateLimiter, SecClient


@pytest.mark.parametrize("rate", [0, -1])
def test_rate_limiter_rejects_non_positive_rate(rate):
    with pytest.raises(ValueError):
        RateLimiter(rate)


def test_default_user_agent_and_rate_come_from_settings():
    c = SecClient()
    s = get_settings()
    assert c.user_agent == s.sec_user_agent
    assert c.http.headers["User-Agent"] == s.sec_user_agent
    assert c.limiter.interval == pytest.approx(1 / s.sec_max_rps)
    assert s.sec_max_rps <= 10


def test_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr(sec_client.time, "sleep", lambda s: None)
    codes = iter([429, 503, 200])
    client = SecClient("ua x@example.com", 10, transport=httpx.MockTransport(
        lambda req: httpx.Response(next(codes), content=b"ok")))
    assert client.get_bytes("https://data.sec.gov/x") == b"ok"
    assert client.network_calls == 3


def test_404_raises_and_writes_no_cache(tmp_path):
    client = SecClient("ua x@example.com", 10, transport=httpx.MockTransport(
        lambda req: httpx.Response(404)))
    cache = tmp_path / "sub" / "x.json"
    with pytest.raises(httpx.HTTPStatusError):
        client.get_json_cached("https://data.sec.gov/x", cache)
    assert not cache.exists()
