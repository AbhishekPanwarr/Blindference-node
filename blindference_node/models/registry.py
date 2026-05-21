"""Model registry — routes ``model_id`` to the right inference backend."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from blindference_node.models.base import ModelBackend

logger = logging.getLogger("blindference-node.models")


class ModelRegistry:
    """Collects :class:`ModelBackend` instances and routes execution."""

    def __init__(self) -> None:
        self._backends: dict[str, ModelBackend] = {}
        # model_id → backend_name
        self._model_map: dict[str, str] = {}

    def register(self, backend: ModelBackend) -> None:
        """Add a backend to the registry."""
        name = backend.name()
        self._backends[name] = backend
        for model_id in backend.supported_models():
            if model_id == "*":
                continue  # wildcard handled specially in run()
            self._model_map[model_id] = name
        logger.debug(
            "Registered backend '%s' with %d model(s)",
            name,
            len(backend.supported_models()),
        )

    def available_backends(self) -> list[str]:
        """Return names of backends whose ``is_available()`` is ``True``."""
        return [name for name, be in self._backends.items() if be.is_available()]

    def available_models(self) -> list[str]:
        """Return model IDs from backends that are available right now."""
        available = self.available_backends()
        return [mid for mid, be_name in self._model_map.items() if be_name in available]

    def run(self, model_id: str, prompt: str) -> str:
        """Execute inference for *model_id* using the first matching backend.

        Resolution order:
            1. Exact model_id match from an available backend.
            2. Wildcard fallback (MockBackend) if no exact match.

        Raises ``ValueError`` if no backend can handle the request.
        """
        # 1 — Exact match from an available backend
        backend_name = self._model_map.get(model_id)
        if backend_name:
            backend = self._backends[backend_name]
            if backend.is_available():
                return backend.run(model_id, prompt)
            logger.warning(
                "Backend '%s' registered for '%s' but is not available",
                backend_name,
                model_id,
            )

        # 2 — Wildcard fallback (mock)
        for be in self._backends.values():
            if "*" in be.supported_models() and be.is_available():
                logger.warning(
                    "No exact backend for '%s' — falling back to '%s'",
                    model_id,
                    be.name(),
                )
                return be.run(model_id, prompt)

        raise ValueError(
            f"No available backend for model '{model_id}'. "
            f"Available backends: {self.available_backends()}"
        )

    def status_table(self) -> list[dict[str, str]]:
        """Return a list of row dicts for CLI tabular display."""
        rows = []
        for be in self._backends.values():
            models = be.supported_models()
            models_str = ", ".join(models) if models != ["*"] else "(all — fallback)"
            rows.append({
                "backend": be.name(),
                "available": "✓" if be.is_available() else "✗",
                "models": models_str,
            })
        return rows
