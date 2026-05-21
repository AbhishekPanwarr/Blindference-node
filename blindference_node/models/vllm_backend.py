"""vLLM local GPU backend — small 125M param model for testing."""

from __future__ import annotations

import logging

from blindference_node.models.base import ModelBackend
from blindference_node.utils import detect_gpu

logger = logging.getLogger("blindference-node.models.vllm")

# Small model for dev / testing — facebook/opt-125m (~125M params, ~250MB)
# Tier 0 so it participates in all quorums alongside cloud API nodes.
LOCAL_MODEL = "facebook/opt-125m"
MIN_VRAM_GB = 0.5


class VLLMBackend(ModelBackend):
    """Local GPU inference via vLLM (deterministic: temperature=0, seed=42).

    Uses a tiny 125M-parameter model so even modest GPUs / CPU-offload
    can run it.  Tier 0 — eligible for all quorums.
    """

    def __init__(self) -> None:
        self._available: bool | None = None
        self._vram_gb: float = 0.0

    def name(self) -> str:
        return "vllm"

    def _probe(self) -> None:
        """Probe GPU availability once and cache result."""
        if self._available is not None:
            return
        try:
            import vllm  # noqa: F401
            _gpu_name, vram_gb = detect_gpu()
            self._available = vram_gb >= MIN_VRAM_GB
            self._vram_gb = vram_gb
        except (ImportError, ModuleNotFoundError):
            self._available = False
            self._vram_gb = 0.0

    def is_available(self) -> bool:
        self._probe()
        return bool(self._available)

    def supported_models(self) -> list[str]:
        self._probe()
        return [LOCAL_MODEL] if self._available else []

    def run(self, model_id: str, prompt: str) -> str:
        from vllm import LLM, SamplingParams

        logger.info("vLLM inference: model=%s (VRAM=%.1fGiB)", model_id, self._vram_gb)
        llm = LLM(
            model=model_id,
            enforce_eager=True,
            seed=42,
            dtype="float16",
        )
        params = SamplingParams(
            temperature=0,
            top_p=1,
            top_k=-1,
            seed=42,
            max_tokens=2048,
        )
        output = llm.generate([prompt], params)[0]
        result = output.outputs[0].text
        logger.info("vLLM inference complete (%d chars)", len(result))
        return result
