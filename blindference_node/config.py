"""Configuration management for the Blindference node."""

import json
import os
import sys
from typing import Any

from pydantic import BaseModel, Field

_ENV_CONFIG_DIR = os.environ.get("BLF_CONFIG_DIR", "")
DEFAULT_CONFIG_DIR = os.path.expanduser(_ENV_CONFIG_DIR) if _ENV_CONFIG_DIR else os.getcwd()
DEFAULT_CONFIG_PATH = os.path.join(DEFAULT_CONFIG_DIR, "config.json")


class Config(BaseModel):
    """Blindference node configuration.

    All fields can be overridden by environment variables prefixed with ``BLF_``.
    For example, ``BLF_LOG_LEVEL=DEBUG`` overrides ``log_level``.
    """

    node_address: str = ""
    keystore_path: str = os.path.join(DEFAULT_CONFIG_DIR, "keystore.json")
    tier: int = Field(default=0, ge=0, le=2)
    supported_model_ids: list[str] = Field(default_factory=list)
    attestation_backend: str = "mock"
    icl_endpoint: str = "https://icl.blindference.xyz"
    payment_service_url: str = "http://127.0.0.1:8001"
    rpc_url: str = ""
    ipfs_gateway: str = "https://node.lighthouse.storage"
    model_cache_dir: str = os.path.join(DEFAULT_CONFIG_DIR, "models")
    log_level: str = "INFO"
    zdr_compliant: bool = False
    network: str = "arbitrum_sepolia"
    attestation_cert_hash: str = ""
    attestation_expiry: int = 0
    registered_on_chain: bool = False
    stake_amount_wei: int = 0
    cofhe_mode: str = "bridge"
    cofhe_endpoint: str = ""
    cofhe_chain_id: int = 421614
    skip_output_key_storage: bool = False
    custom_backends: list[str] = Field(default_factory=list)


def _env_override(key: str, value: Any) -> Any:
    """Resolve environment variable override for a config field."""
    env_key = f"BLF_{key.upper()}"
    env_val = os.environ.get(env_key)
    if env_val is None:
        return value

    if isinstance(value, bool):
        return env_val.lower() in ("1", "true", "yes")
    if isinstance(value, int):
        return int(env_val)
    if isinstance(value, list):
        return [item.strip() for item in env_val.split(",") if item.strip()]
    return env_val


def _expand_paths(config: Config) -> Config:
    """Expand ``~`` in all path fields."""
    for field in ("keystore_path", "model_cache_dir"):
        value = getattr(config, field)
        if value and isinstance(value, str):
            setattr(config, field, os.path.expanduser(value))
    return config


def load_config(path: str | None = None) -> Config:
    """Load configuration from a JSON file, applying environment overrides.

    Args:
        path: Path to the config file. Defaults to ``./config.json`` in the current working directory.

    Returns:
        A ``Config`` instance.

    Raises:
        SystemExit: if the file exists but contains invalid JSON or fails validation.
    """
    file_path = path or DEFAULT_CONFIG_PATH

    if not os.path.exists(file_path):
        config = Config()
    else:
        try:
            with open(file_path) as f:
                raw = json.load(f)
            config = Config.model_validate(raw)
        except (json.JSONDecodeError, ValueError) as exc:
            print(f"Error: Could not parse config file {file_path}: {exc}", file=sys.stderr)
            raise SystemExit(1)

    # Apply environment overrides
    for name, field in Config.model_fields.items():
        current = getattr(config, name)
        setattr(config, name, _env_override(name, current))

    return _expand_paths(config)


def save_config(config: Config, path: str | None = None) -> None:
    """Save configuration to a JSON file.

    Creates the parent directory if it doesn't exist.

    Args:
        config: The ``Config`` instance to save.
        path: Target path. Defaults to ``./config.json`` in the current working directory.
    """
    file_path = path or DEFAULT_CONFIG_PATH
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    raw = config.model_dump()
    with open(file_path, "w") as f:
        json.dump(raw, f, indent=2)
