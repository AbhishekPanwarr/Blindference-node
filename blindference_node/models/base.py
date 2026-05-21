"""Abstract base class for model inference backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ModelBackend(ABC):
    """Pluggable inference backend.

    Each backend advertises a set of model IDs it can run, declares
    whether it is *available* on the current machine (GPU present, API
    key set, etc.), and implements deterministic execution.
    """

    @abstractmethod
    def name(self) -> str:
        """Human-readable backend name (e.g. ``"groq"``, ``"vllm"``)."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return ``True`` if this backend can execute right now.

        Checks are cheap and idempotent — called during registry setup
        and CLI introspection.
        """

    @abstractmethod
    def supported_models(self) -> list[str]:
        """Return the list of model IDs this backend advertises.

        Example: ``["groq:llama-3.3-70b-versatile"]``.
        """

    @abstractmethod
    def run(self, model_id: str, prompt: str) -> str:
        """Execute deterministic inference.

        Must produce byte-identical output for the same
        ``(model_id, prompt)`` pair (within the same backend version).

        Raises on unrecoverable failure — the caller decides whether
        to retry or fall back to another backend.
        """
