"""Tests for blindference_node.execution."""

import hashlib

import pytest

from blindference_node.execution import run_deterministic_inference, run_determinism_self_test


def test_deterministic_output():
    """Same (model_id, prompt) → identical hex output."""
    output1 = run_deterministic_inference("qwen2.5-7b", "Hello")
    output2 = run_deterministic_inference("qwen2.5-7b", "Hello")
    assert output1 == output2
    assert output1.startswith("MOCK_OUTPUT_")
    assert len(output1) == len("MOCK_OUTPUT_") + 64  # hex sha256


def test_different_prompt_different_output():
    """Different prompts yield different outputs."""
    o1 = run_deterministic_inference("qwen2.5-7b", "Hello")
    o2 = run_deterministic_inference("qwen2.5-7b", "World")
    assert o1 != o2


def test_different_model_different_output():
    """Different models yield different outputs for the same prompt."""
    o1 = run_deterministic_inference("qwen2.5-7b", "Hello")
    o2 = run_deterministic_inference("llama3.1-70b", "Hello")
    assert o1 != o2


def test_self_test_passes():
    """The self‑test returns True in normal conditions."""
    assert run_determinism_self_test() is True
