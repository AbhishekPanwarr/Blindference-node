"""Real‑GPU determinism test — only runs with vLLM installed."""

import pytest

try:
    from vllm import LLM, SamplingParams  # noqa: F401
    HAS_GPU = True
except (ImportError, ModuleNotFoundError):
    HAS_GPU = False

pytestmark = pytest.mark.skipif(
    not HAS_GPU,
    reason="vLLM not installed — install GPU extras: pip install blindference-node[gpu]",
)


def test_determinism_with_opt125m():
    """Run the determinism self‑test with facebook/opt‑125m (125M params, ~500 MB VRAM)."""
    from blindference_node.execution import run_determinism_self_test

    assert run_determinism_self_test(
        model_id="facebook/opt-125m",
        test_prompt="What is the capital of France?",
    ) is True
