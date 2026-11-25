"""LiteLLM gateway: key pool with automatic failover + built-in response cache."""
import logging
from dataclasses import dataclass

import litellm
from litellm import Cache

from .config import settings

log = logging.getLogger("chatbot.llm")

litellm.drop_params = True
litellm.cache = Cache(type="local")  # LiteLLM's built-in in-memory cache

ALLOWED_SIM_STATUSES = {429, 500, 502, 503}


class AllProvidersUnavailable(Exception):
    pass


@dataclass
class LLMResult:
    reply: str
    resolution_source: str  # LIVE_INFERENCE | LLM_CACHE
    input_tokens: int
    output_tokens: int
    key_id: str | None
    fallback_attempts: int


def parse_simulation(header: str | None) -> dict[str, int]:
    """'key_1=429,key_2=500' or '*=429' -> {'key_1': 429, ...}. Bad pairs are ignored."""
    result: dict[str, int] = {}
    if not header:
        return result
    for pair in header.split(","):
        name, sep, status = pair.strip().partition("=")
        if not sep:
            continue
        try:
            code = int(status.strip())
        except ValueError:
            continue
        if code in ALLOWED_SIM_STATUSES and name.strip():
            result[name.strip()] = code
    return result


async def complete(messages: list[dict], simulated: dict[str, int]) -> LLMResult:
    """Try each key in order. First success wins; every failure moves to the next key."""
    failed = 0
    for index, api_key in enumerate(settings.api_keys, start=1):
        key_id = f"key_{index}"
        sim_status = simulated.get(key_id, simulated.get("*"))
        if sim_status is not None:
            log.warning("%s: simulated failure %s", key_id, sim_status)
            failed += 1
            continue
        try:
            kwargs = dict(
                model=settings.model,
                messages=messages,
                api_key=api_key,
                timeout=settings.llm_timeout,
                num_retries=0,  # we do our own key failover; no hidden retries
                caching=True,
            )
            if simulated:
                # Failover demo requests must hit a live key, so skip cache reads.
                kwargs["cache"] = {"no-cache": True}
            response = await litellm.acompletion(**kwargs)
            reply = (response.choices[0].message.content or "").strip()
            if not reply:
                raise ValueError("empty completion")
        except Exception as exc:  # 429, quota, 5xx, timeouts, auth errors -> next key
            log.warning("%s failed: %s: %s", key_id, type(exc).__name__, str(exc)[:200])
            failed += 1
            continue

        cache_hit = bool(getattr(response, "_hidden_params", {}).get("cache_hit"))
        usage = getattr(response, "usage", None)
        return LLMResult(
            reply=reply,
            resolution_source="LLM_CACHE" if cache_hit else "LIVE_INFERENCE",
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            key_id=None if cache_hit else key_id,
            fallback_attempts=0 if cache_hit else failed,
        )
    raise AllProvidersUnavailable()
