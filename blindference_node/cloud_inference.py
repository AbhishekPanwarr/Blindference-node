"""Cloud inference fallback — Groq / Gemini API for nodes without GPU."""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("blindference-node.execution")

# Model ID → cloud provider mapping (only two active cloud models)
_CLOUD_MODEL_MAP: dict[str, tuple[str, str]] = {
    "groq:llama-3.3-70b-versatile": ("groq", "llama-3.3-70b-versatile"),
    "gemini:gemini-2.5-flash": ("gemini", "gemini-2.5-flash-preview-04-09"),
}


def _cloud_provider_for_model(model_id: str) -> tuple[str, str] | None:
    """Return (provider, api_model_id) or None if not a cloud model."""
    return _CLOUD_MODEL_MAP.get(model_id)


def _has_cloud_credentials(provider: str) -> bool:
    """Check whether API key for *provider* is present in environment."""
    if provider == "groq":
        return bool(os.environ.get("GROQ_API_KEY"))
    if provider == "gemini":
        return bool(os.environ.get("GOOGLE_API_KEY"))
    return False


def _deterministic_cloud_prompt(model_id: str, prompt: str) -> str:
    """Wrap prompt with a lightweight seed marker so the cloud API
    produces (near-)identical output across repeated calls with the same
    ``(model_id, prompt)`` pair.

    Groq natively supports ``seed`` + ``temperature=0`` for determinism.
    Gemini does not expose a seed parameter, so we prepend a hash-derived
    anchor to reduce temperature-driven variance without restricting
    response creativity for *different* prompts.
    """
    h = hashlib.sha256(f"{model_id}:{prompt}".encode()).hexdigest()[:16]
    # The anchor is a single neutral sentence; it must NOT tell the model
    # to "be consistent" or "do not vary wording" — that causes generic
    # boilerplate responses that ignore the actual user query.
    return f"[seed_anchor:{h}]\n\n{prompt}"


async def _groq_generate(model_id: str, prompt: str, api_key: str) -> str:
    """Call Groq chat-completions API asynchronously."""
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": "You are a helpful assistant. Answer the user's question directly and accurately. Be concise."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_completion_tokens": 512,
        "seed": 42,
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Groq API returned {resp.status}: {text}")
            data = await resp.json()
            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError("Groq API returned empty choices")
            return choices[0]["message"]["content"]


async def _gemini_generate(model_id: str, prompt: str, api_key: str) -> str:
    """Call Gemini generateContent API asynchronously."""
    # Gemini model IDs in the API use a different naming scheme
    gemini_model = model_id  # e.g. gemini-2.5-flash-preview-04-09
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{gemini_model}:generateContent?key={api_key}"
    )
    headers = {"Content-Type": "application/json"}
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ],
        "generationConfig": {
            "temperature": 0.0,
            "maxOutputTokens": 512,
        },
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"Gemini API returned {resp.status}: {text}")
            data = await resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini API returned empty candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise RuntimeError("Gemini API returned empty parts")
            return parts[0]["text"]


async def run_cloud_inference(model_id: str, prompt: str) -> str | None:
    """Try to run inference via a cloud provider API (Groq or Gemini).

    Returns ``None`` if:
        - the model is not a recognised cloud model, or
        - no API key is configured for the provider.

    Raises on API errors.
    """
    mapping = _cloud_provider_for_model(model_id)
    if mapping is None:
        return None

    provider, api_model_id = mapping
    if not _has_cloud_credentials(provider):
        logger.info(
            "Cloud inference for %s requires %s_API_KEY env var (not set)",
            model_id,
            provider.upper(),
        )
        return None

    api_key = os.environ[f"{provider.upper()}_API_KEY"]
    deterministic_prompt = _deterministic_cloud_prompt(model_id, prompt)

    logger.info("Running cloud inference via %s (model=%s) …", provider, api_model_id)
    if provider == "groq":
        result = await _groq_generate(api_model_id, deterministic_prompt, api_key)
    elif provider == "gemini":
        result = await _gemini_generate(api_model_id, deterministic_prompt, api_key)
    else:
        return None

    logger.info("Cloud inference succeeded (%d chars)", len(result))
    return result


def run_mock_inference(model_id: str, prompt: str) -> str:
    """Deterministic mock fallback when neither GPU nor cloud API is available."""
    payload = f"{model_id}:{prompt}".encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()
    result = f"MOCK_OUTPUT_{h}"
    logger.warning(
        "No GPU and no cloud API credentials — using deterministic mock output. "
        "Set GROQ_API_KEY or GOOGLE_API_KEY to run real inference."
    )
    return result


def run_sync(coro, timeout: float = 70.0):
    """Run an async coroutine from a **synchronous** context.

    If the current thread already has a running event loop (e.g. the daemon's
    async job worker), the coroutine is scheduled in a fresh side-thread via
    :class:`concurrent.futures.ThreadPoolExecutor` so ``asyncio.run`` can
    manage its own loop.  Otherwise the existing loop is used directly.

    Args:
        coro: An awaitable (typically the result of an ``async def`` call).
        timeout: Seconds to wait for the coroutine to finish.

    Returns:
        The coroutine's result.

    Raises:
        TimeoutError: if the coroutine does not finish within *timeout*.
        Exception: any exception raised by the coroutine.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread — safe to use run_until_complete
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()

    # A loop is already running (we are inside the daemon's async worker).
    # asyncio.run_until_complete would raise RuntimeError, so we delegate
    # to a side thread that starts its own fresh event loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=timeout)
