"""Backend discovery and registration.

Three loading strategies (in order):

1. **Built-in** — vLLM, Groq, Gemini, Mock are always registered.
2. **Entry points** — any pip package that declares
   ``[project.entry-points."blindference.backends"]`` is auto-discovered.
3. **Config dotted paths** — ``custom_backends`` in ``config.json`` lists
   ``"module.submodule:ClassName"`` strings; imported dynamically at runtime.

Usage::

    from backend_loader import build_registry
    registry = build_registry(config)
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING

from blindference_node.models.vllm_backend import VLLMBackend
from blindference_node.models.groq_backend import GroqBackend
from blindference_node.models.gemini_backend import GeminiBackend
from blindference_node.models.mock_backend import MockBackend

if TYPE_CHECKING:
    from blindference_node.config import Config
    from blindference_node.models.base import ModelBackend
    from blindference_node.models.registry import ModelRegistry

logger = logging.getLogger("blindference-node.backends")


def _register_builtin(registry: ModelRegistry) -> None:
    """Add the four built-in backends."""
    registry.register(VLLMBackend())
    registry.register(GroqBackend())
    registry.register(GeminiBackend())
    registry.register(MockBackend())


def _load_from_dotted_path(dotted: str) -> ModelBackend:
    """Import ``module.submodule:ClassName`` and return an instance.

    Raises ``ImportError`` / ``AttributeError`` / ``ValueError`` on failure.
    """
    if ":" in dotted:
        mod_path, cls_name = dotted.split(":", 1)
    else:
        # Support plain module.ClassName as a convenience
        if "." not in dotted:
            raise ValueError(
                f"Custom backend '{dotted}' must be in the form "
                f"'module.submodule:ClassName' or 'module.ClassName'"
            )
        mod_path, cls_name = dotted.rsplit(".", 1)

    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    if not callable(cls):
        raise ValueError(f"'{dotted}' is not callable")
    instance = cls()
    return instance


def _register_from_config(registry: ModelRegistry, config: Config) -> None:
    """Import and register every backend listed in ``config.custom_backends``."""
    for dotted in config.custom_backends:
        dotted = dotted.strip()
        if not dotted:
            continue
        try:
            backend = _load_from_dotted_path(dotted)
            registry.register(backend)
            logger.info("Registered custom backend '%s' from '%s'", backend.name(), dotted)
        except Exception as exc:
            logger.warning("Could not load custom backend '%s': %s", dotted, exc)


def _register_entry_points(registry: ModelRegistry) -> None:
    """Scan the ``blindference.backends`` entry-point group and register every
    discovered class.

    Packages declare entry points in ``pyproject.toml``::

        [project.entry-points."blindference.backends"]
        llamacpp = "my_package.backends:LlamaCppBackend"
    """
    try:
        from importlib.metadata import entry_points
    except ImportError:  # pragma: no cover
        logger.debug("importlib.metadata not available — skipping entry-point scan")
        return

    try:
        eps = entry_points()
        # Python 3.9 / 3.10 compatibility: entry_points() returns dict-like or SelectableGroups
        if hasattr(eps, "select"):
            group = eps.select(group="blindference.backends")
        else:
            group = eps.get("blindference.backends", [])
    except Exception as exc:
        logger.debug("Failed to read entry points: %s", exc)
        return

    for ep in group:
        try:
            cls = ep.load()
            backend = cls()
            registry.register(backend)
            logger.info(
                "Registered backend '%s' from entry point '%s' (%s)",
                backend.name(),
                ep.name,
                ep.value,
            )
        except Exception as exc:
            logger.warning(
                "Could not load backend from entry point '%s': %s", ep.name, exc
            )


def build_registry(config: Config | None = None) -> ModelRegistry:
    """Create a fully populated :class:`ModelRegistry`.

    Registration order:
        1. Built-in backends (vLLM, Groq, Gemini, Mock).
        2. Entry-point backends (third-party pip packages).
        3. Config-driven dotted paths (``custom_backends`` list).

    Later registrations override earlier ones for the same ``model_id``
    because :meth:`ModelRegistry.register` simply overwrites the internal map.
    """
    from blindference_node.models.registry import ModelRegistry

    registry = ModelRegistry()
    _register_builtin(registry)
    _register_entry_points(registry)
    if config is not None:
        _register_from_config(registry, config)
    return registry
