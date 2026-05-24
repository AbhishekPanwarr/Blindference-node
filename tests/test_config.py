"""Tests for blindference_node.config."""

import json
import os
import tempfile

from blindference_node.config import Config, load_config, save_config


def test_default_config():
    """A default Config has the expected defaults."""
    cfg = Config()
    assert cfg.node_address == ""
    assert cfg.tier == 0
    assert cfg.attestation_backend == "mock"
    assert cfg.log_level == "INFO"
    assert cfg.zdr_compliant is False
    assert cfg.network == "arbitrum_sepolia"


def test_save_and_load_roundtrip():
    """save_config() + load_config() round-trips all fields."""
    data = Config(
        node_address="0x1234567890123456789012345678901234567890",
        tier=2,
        supported_model_ids=["qwen2.5-7b", "llama3.1-70b"],
        log_level="DEBUG",
    )

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tmp_path = tf.name

    try:
        save_config(data, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.node_address == data.node_address
        assert loaded.tier == data.tier
        assert loaded.supported_model_ids == data.supported_model_ids
        assert loaded.log_level == "DEBUG"
    finally:
        os.unlink(tmp_path)


def test_load_config_missing_file_returns_defaults():
    """load_config() with a nonexistent path returns a default Config."""
    cfg = load_config("/tmp/blindference-nonexistent-config.json")
    assert cfg.tier == 0
    assert cfg.node_address == ""


def test_env_override_string():
    """BLF_ env var overrides a string field."""
    os.environ["BLF_LOG_LEVEL"] = "CRITICAL"
    try:
        cfg = load_config()
        assert cfg.log_level == "CRITICAL"
    finally:
        del os.environ["BLF_LOG_LEVEL"]


def test_env_override_int():
    """BLF_TIER overrides the tier field."""
    os.environ["BLF_TIER"] = "1"
    try:
        cfg = load_config()
        assert cfg.tier == 1
    finally:
        del os.environ["BLF_TIER"]


def test_env_override_list():
    """BLF_SUPPORTED_MODEL_IDS overrides as comma-separated list."""
    os.environ["BLF_SUPPORTED_MODEL_IDS"] = "qwen2.5-7b,llama3.1-70b"
    try:
        cfg = load_config()
        assert cfg.supported_model_ids == ["qwen2.5-7b", "llama3.1-70b"]
    finally:
        del os.environ["BLF_SUPPORTED_MODEL_IDS"]


def test_env_override_bool():
    """BLF_ZDR_COMPLIANT overrides a bool field."""
    os.environ["BLF_ZDR_COMPLIANT"] = "1"
    try:
        cfg = load_config()
        assert cfg.zdr_compliant is True
    finally:
        del os.environ["BLF_ZDR_COMPLIANT"]


def test_new_fields_have_defaults():
    """Phase 2 fields have sensible defaults."""
    cfg = Config()
    assert cfg.attestation_cert_hash == ""
    assert cfg.attestation_expiry == 0
    assert cfg.stake_amount_wei == 0


def test_new_fields_save_and_load():
    """Phase 2 fields persist through save/load round-trip."""
    data = Config(
        attestation_cert_hash="0xdeadbeef",
        attestation_expiry=1234567890,
        stake_amount_wei=100000,
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tf:
        tmp_path = tf.name

    try:
        save_config(data, tmp_path)
        loaded = load_config(tmp_path)
        assert loaded.attestation_cert_hash == "0xdeadbeef"
        assert loaded.attestation_expiry == 1234567890
        assert loaded.stake_amount_wei == 100000
    finally:
        os.unlink(tmp_path)


def test_env_override_stake_amount():
    """BLF_STAKE_AMOUNT_WEI overrides stake_amount_wei."""
    os.environ["BLF_STAKE_AMOUNT_WEI"] = "500000"
    try:
        cfg = load_config()
        assert cfg.stake_amount_wei == 500000
    finally:
        del os.environ["BLF_STAKE_AMOUNT_WEI"]
