"""HTTP calls from the UI to the API: streamed /ask/stream with a fallback to /ask."""

from collections.abc import Callable

import httpx

from ui.sse import iter_events

START_HINT = "start it with `uv run uvicorn src.api.main:app --port 8000`"


class ApiError(Exception):
    """A failure to show the user as is."""


def _unreachable(api_url: str) -> ApiError:
    return ApiError(f"API not reachable at {api_url}; {START_HINT}")


def _http_error(r: httpx.Response) -> ApiError:
    return ApiError(f"API returned HTTP {r.status_code}: {r.text[:300]}")


def health(api_url: str) -> str | None:
    """None when GET /health answers ok, else a short error message."""
    try:
        with httpx.Client(timeout=3.0) as c:
            r = c.get(f"{api_url}/health")
    except httpx.HTTPError:
        return f"not reachable at {api_url}"
    if r.status_code != 200:
        return f"HTTP {r.status_code} from {api_url}/health"
    return None


def ask(api_url: str, question: str, on_step: Callable[[dict], None]) -> dict:
    """Ask the API; call on_step(step) for each step as it arrives; return the AskResponse
    JSON. Uses POST /ask/stream; if that endpoint is missing (404/501), POST /ask and replay
    its steps afterwards. Raises ApiError with a user-facing message on any failure."""
    # No read timeout: agent answers take 20-110 s, and steps arrive at irregular intervals.
    timeout = httpx.Timeout(10.0, read=None)
    try:
        with httpx.Client(timeout=timeout) as c:
            with c.stream("POST", f"{api_url}/ask/stream", json={"question": question}) as r:
                if r.status_code not in (404, 501):
                    if r.status_code >= 400:
                        r.read()
                        raise _http_error(r)
                    return _consume(r, on_step)
            r = c.post(f"{api_url}/ask", json={"question": question})
            if r.status_code >= 400:
                raise _http_error(r)
            resp = r.json()
            for step in resp.get("steps", []):
                on_step(step)
            return resp
    except httpx.ConnectError as e:
        raise _unreachable(api_url) from e
    except httpx.HTTPError as e:
        raise ApiError(f"Request to the API at {api_url} failed: {type(e).__name__}: {e}") from e


def _consume(r: httpx.Response, on_step: Callable[[dict], None]) -> dict:
    for event in iter_events(r.iter_lines()):
        kind, data = event.get("type"), event.get("data")
        if kind == "step":
            on_step(data)
        elif kind == "final":
            return data
        elif kind == "error":
            msg = data.get("message") if isinstance(data, dict) else data
            raise ApiError(f"The API reported an error: {msg}")
    raise ApiError("The answer stream ended without a final answer.")
