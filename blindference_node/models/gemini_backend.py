"""Gemini cloud API backend for nodes without local GPU."""

from __future__ import annotations

import logging
import os

from blindference_node.models.base import ModelBackend
from blindference_node.cloud_inference import (
    _gemini_generate,
    _deterministic_cloud_prompt,
    run_sync,
)

logger = logging.getLogger("blindference-node.models.gemini")


class GeminiBackend(ModelBackend):
    """Google Gemini inference via the generateContent REST API."""

    _MODEL_IDS = [
        "gemini:gemini-2.5-flash",
    ]

    def name(self) -> str:
        return "gemini"

    def is_available(self) -> bool:
        return bool(os.environ.get("GOOGLE_API_KEY"))

    def supported_models(self) -> list[str]:
        return list(self._MODEL_IDS)

    def run(self, model_id: str, prompt: str) -> str:
        api_key = os.environ["GOOGLE_API_KEY"]
        deterministic_prompt = _deterministic_cloud_prompt(model_id, prompt)
        api_model_id = model_id.replace("gemini:", "")

        logger.info("Gemini inference: model=%s", api_model_id)
        try:
            result = run_sync(
                _gemini_generate(api_model_id, deterministic_prompt, api_key)
            )
            logger.info("Gemini inference complete (%d chars)", len(result))
            return result
        except Exception as exc:
            logger.error("Gemini inference failed: %s", exc)
            raise
