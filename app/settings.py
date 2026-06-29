"""Runtime settings read lazily from environment variables.

The LLM is fully optional: when disabled or unkeyed, the service runs as a pure
deterministic rule engine.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def use_llm() -> bool:
    return os.getenv("USE_LLM", "false").strip().lower() in _TRUTHY


def api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY", "") or "").strip()


def llm_enabled() -> bool:
    return use_llm() and bool(api_key())


def model() -> str:
    return os.getenv("LLM_MODEL", "google/gemini-2.5-flash").strip()


def base_url() -> str:
    return os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")


def timeout_seconds() -> float:
    try:
        return float(os.getenv("LLM_TIMEOUT_SECONDS", "4.5"))
    except (TypeError, ValueError):
        return 4.5


def connect_timeout_seconds() -> float:
    try:
        return float(os.getenv("LLM_CONNECT_TIMEOUT_SECONDS", "2.0"))
    except (TypeError, ValueError):
        return 2.0


def max_concurrent_llm() -> int:
    """Upper bound on in-flight outbound LLM calls; excess requests use the rule
    answer rather than queueing behind the provider."""
    try:
        return max(1, int(os.getenv("LLM_MAX_CONCURRENCY", "8")))
    except (TypeError, ValueError):
        return 8
