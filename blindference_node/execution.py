"""Deterministic inference execution with vLLM fallback."""

import hashlib


def run_deterministic_inference(model_id: str, prompt: str) -> str:
    """Run deterministic LLM inference.

    Tries real vLLM (temperature=0, seed=42, enforce_eager=True) when
    the optional GPU dependencies are installed.  Falls back to a mock
    SHA‑256-based output when vLLM is not available.

    Args:
        model_id: The model to use (e.g. ``"qwen2.5-7b"``).
        prompt: The plaintext input prompt.

    Returns:
        A deterministic string — identical for the same ``(model_id, prompt)``
        pair across any invocation.
    """
    try:
        from vllm import LLM, SamplingParams

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
        return output.outputs[0].text

    except (ImportError, ModuleNotFoundError):
        pass

    # Mock fallback — deterministic per (model_id, prompt)
    payload = f"{model_id}:{prompt}".encode("utf-8")
    h = hashlib.sha256(payload).hexdigest()
    return f"MOCK_OUTPUT_{h}"


def run_determinism_self_test() -> bool:
    """Verify that ``run_deterministic_inference`` produces identical output
    for the same input across two independent calls.

    Returns:
        ``True`` if the self‑test passes.

    Raises:
        RuntimeError: if the outputs differ.
    """
    test_prompt = "Hello, Blindference"
    test_model = "qwen2.5-7b"

    output1 = run_deterministic_inference(test_model, test_prompt)
    output2 = run_deterministic_inference(test_model, test_prompt)

    if output1 != output2:
        raise RuntimeError(
            f"Determinism self‑test FAILED: outputs differ for same input.\n"
            f"  Run 1: {output1}\n"
            f"  Run 2: {output2}"
        )

    return True
