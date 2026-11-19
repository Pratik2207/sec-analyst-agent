import httpx

from src.sec_client import RateLimiter, SecClient


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def test_rate_limiter_never_exceeds_rate():
    clock = FakeClock()
    rl = RateLimiter(10, clock=clock.now, sleep=clock.sleep)
    stamps = []
    for _ in range(50):
        rl.wait()
        stamps.append(clock.t)
    # any 1-second window holds at most 10 calls
    for i in range(len(stamps) - 10):
        assert stamps[i + 10] - stamps[i] >= 1.0 - 1e-9


def test_user_agent_header_and_cache(tmp_path):
    seen = []

    def handler(request):
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, json={"ok": 1})

    client = SecClient("test-agent test@example.com", 10, transport=httpx.MockTransport(handler))
    cache = tmp_path / "x.json"
    assert client.get_json_cached("https://data.sec.gov/x", cache) == {"ok": 1}
    assert client.get_json_cached("https://data.sec.gov/x", cache) == {"ok": 1}
    assert seen == ["test-agent test@example.com"]
    assert client.network_calls == 1
