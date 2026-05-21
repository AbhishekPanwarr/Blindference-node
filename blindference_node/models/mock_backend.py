"""Deterministic mock fallback backend."""

from __future__ import annotations

import hashlib
import logging

from blindference_node.models.base import ModelBackend

logger = logging.getLogger("blindference-node.models.mock")


class MockBackend(ModelBackend):
    """Deterministic mock inference — SHA-256 of ``(model_id, prompt)``.

    This backend is *always* available and registers for **all** model IDs
    as a universal fallback.  It produces consistent output for the same
    input so the quorum commitment scheme still works.
    """

    def name(self) -> str:
        return "mock"

    def is_available(self) -> bool:
        return True

    def supported_models(self) -> list[str]:
        # Universal fallback — accepts any model_id
        return ["*"]

    def run(self, model_id: str, prompt: str) -> str:
        logger.warning(
            "Mock fallback for model=%s — no real GPU or API backend available. "
            "Set GROQ_API_KEY or GOOGLE_API_KEY for real inference.",
            model_id,
        )
        payload = f"{model_id}:{prompt}".encode("utf-8")
        h = hashlib.sha256(payload).hexdigest()
        result = f"MOCK_OUTPUT_{h}"
        logger.debug("Mock result: %s…", result[:32])
        return result
