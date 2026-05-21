"""Groq cloud API backend for nodes without local GPU."""

from __future__ import annotations

import logging
import os

from blindference_node.models.base import ModelBackend
from blindference_node.cloud_inference import (
    _groq_generate,
    _deterministic_cloud_prompt,
    run_sync,
)

logger = logging.getLogger("blindference-node.models.groq")


class GroqBackend(ModelBackend):
    """Groq-hosted LLM inference via OpenAI-compatible chat-completions API."""

    _MODEL_IDS = [
        "groq:llama-3.3-70b-versatile",
    ]

    def name(self) -> str:
        return "groq"

    def is_available(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))

    def supported_models(self) -> list[str]:
        return list(self._MODEL_IDS)

    def run(self, model_id: str, prompt: str) -> str:
        api_key = os.environ["GROQ_API_KEY"]
        deterministic_prompt = _deterministic_cloud_prompt(model_id, prompt)
        api_model_id = model_id.replace("groq:", "")

        logger.info("Groq inference: model=%s", api_model_id)
        try:
            result = run_sync(
                _groq_generate(api_model_id, deterministic_prompt, api_key)
            )
            logger.info("Groq inference complete (%d chars)", len(result))
            return result
        except Exception as exc:
            logger.error("Groq inference failed: %s", exc)
            raise
