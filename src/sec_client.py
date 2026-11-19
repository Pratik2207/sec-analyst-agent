"""SEC EDGAR HTTP client: compliant User-Agent, <= N requests/second, local file cache."""

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from config.settings import get_settings


class RateLimiter:
    """Allows at most `rate` calls per second by spacing calls 1/rate seconds apart."""

    def __init__(
        self,
        rate: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.interval = 1.0 / rate
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            now = self._clock()
            if now < self._next:
                self._sleep(self._next - now)
                now = self._next
            self._next = now + self.interval


class SecClient:
    def __init__(self, user_agent: str | None = None, max_rps: float | None = None,
                 transport: httpx.BaseTransport | None = None):
        settings = get_settings() if user_agent is None or max_rps is None else None
        self.user_agent = user_agent or settings.sec_user_agent
        self.limiter = RateLimiter(max_rps or settings.sec_max_rps)
        self.http = httpx.Client(
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            timeout=60,
            transport=transport,
        )
        self.network_calls = 0

    def get_bytes(self, url: str, retries: int = 3) -> bytes:
        for attempt in range(retries):
            self.limiter.wait()
            self.network_calls += 1
            resp = self.http.get(url)
            if resp.status_code in (429, 500, 502, 503) and attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.content
        raise RuntimeError("unreachable")

    def get_json_cached(self, url: str, cache_path: Path) -> dict:
        """Return JSON from `cache_path` if present; otherwise download and cache it."""
        if cache_path.exists():
            return json.loads(cache_path.read_bytes())
        body = self.get_bytes(url)
        data = json.loads(body)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(body)
        return data
