"""Deterministic inference execution using the pluggable backend registry.

All backends are collected once at import time; ``run_deterministic_inference``
just delegates to :class:`models.registry.ModelRegistry`.

The registry is built lazily on first use.  For config-driven custom backends
(``custom_backends`` in ``config.json``) call :func:`set_registry` or pass a
:class:`~blindference_node.config.Config` object to :func:`get_registry` *before*
any inference runs.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from blindference_node.backend_loader import build_registry

if TYPE_CHECKING:
    from blindference_node.config import Config
    from blindference_node.models.registry import ModelRegistry

logger = logging.getLogger("blindference-node.execution")


# Module-level singleton — backends are probed lazily on first use.
_REGISTRY: ModelRegistry | None = None


def get_registry(config: Config | None = None) -> ModelRegistry:
    """Return the global :class:`ModelRegistry`, creating it on first call.

    If ``config`` is provided and the registry has not been created yet, the
    config-driven ``custom_backends`` dotted paths are loaded as well.
    """
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = build_registry(config)
    return _REGISTRY


def set_registry(config: Config | None = None) -> ModelRegistry:
    """Force-rebuild the global registry (useful after config changes).

    Returns the newly built registry.
    """
    global _REGISTRY
    _REGISTRY = build_registry(config)
    return _REGISTRY


def run_deterministic_inference(model_id: str, prompt: str) -> str:
    """Run deterministic LLM inference through the backend registry.

    Resolution order (handled by :meth:`ModelRegistry.run`):

        1. **Exact match** from an available backend (vLLM, Groq, Gemini, or
           any custom / entry-point backend).
        2. **Mock fallback** — SHA-256-based deterministic string.

    Args:
        model_id: The model to use (e.g. ``"qwen2.5-7b"``,
            ``"groq:llama-3.3-70b-versatile"``, ``"gemini:gemini-2.5-flash"``).
        prompt: The plaintext input prompt.

    Returns:
        A deterministic string — identical for the same ``(model_id, prompt)``
        pair across any invocation (within the same backend).
    """
    registry = get_registry()
    logger.debug("Inference request: model=%s", model_id)
    return registry.run(model_id, prompt)


def run_determinism_self_test(
    model_id: str = "facebook/opt-125m",
    test_prompt: str = "Hello, Blindference",
) -> bool:
    """Verify that ``run_deterministic_inference`` produces identical output
    for the same input across two independent calls.

    Args:
        model_id: The model to test. Defaults to ``"qwen2.5-7b"``.
            Use ``"facebook/opt-125m"`` for a lightweight GPU test (~500 MB VRAM).
        test_prompt: The prompt to use for both runs.

    Returns:
        ``True`` if the self-test passes.

    Raises:
        RuntimeError: if the outputs differ.
    """
    output1 = run_deterministic_inference(model_id, test_prompt)
    output2 = run_deterministic_inference(model_id, test_prompt)

    if output1 != output2:
        raise RuntimeError(
            f"Determinism self-test FAILED: outputs differ for same input.\n"
            f"  Run 1: {output1}\n"
            f"  Run 2: {output2}"
        )

    return True
