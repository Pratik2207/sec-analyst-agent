"""Phase 4 contract: the one way agent code calls Ollama. Tests stub `chat_json`.

chat_json(model, system, user, schema, think=False) -> (parsed JSON dict, Tokens)
Raises LLMError for transport failures, empty replies and invalid JSON, so callers can
fall back instead of crashing /ask.
"""

import json

import httpx
import ollama

from config.settings import get_settings
from src.api.schemas import Tokens

KEEP_ALIVE = "5m"


class LLMError(RuntimeError):
    pass


def _strip_reasoning(text: str) -> str:
    """Thinking-only builds can leak "...</think>" into content; keep what follows."""
    return text.rsplit("</think>", 1)[-1].strip()


def chat_json(model: str, system: str, user: str, schema: dict,
              think: bool = False) -> tuple[dict, Tokens]:
    s = get_settings()
    try:
        resp = ollama.Client(host=s.ollama_host, timeout=s.llm_timeout_s).chat(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            format=schema, think=think,
            # Ollama defaults to a 4096-token context; multi-hop evidence + feedback exceeds it.
            options={"temperature": 0, "num_ctx": s.llm_num_ctx}, keep_alive=KEEP_ALIVE)
    except (ollama.ResponseError, ollama.RequestError, httpx.HTTPError, ConnectionError) as e:
        raise LLMError(f"{model}: {type(e).__name__}: {e}") from e
    tokens = Tokens(prompt=resp.prompt_eval_count or 0, completion=resp.eval_count or 0)
    text = _strip_reasoning(resp.message.content or "")
    if not text:
        raise LLMError(f"{model}: empty reply")
    try:
        return json.loads(text), tokens
    except json.JSONDecodeError as e:
        raise LLMError(f"{model}: invalid JSON: {text[:200]!r}") from e
