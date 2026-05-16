"""Tests for blindference_node.wallet."""

import json
import os
import tempfile

import pytest

from blindference_node.wallet import generate_wallet, import_wallet, load_wallet


def test_generate_wallet_creates_valid_address():
    """generate_wallet() returns a checksummed hex address and creates a keystore."""
    with tempfile.TemporaryDirectory() as tmp:
        keystore = os.path.join(tmp, "keystore.json")
        password = "test-password"

        address = generate_wallet(keystore, password)

        assert address.startswith("0x")
        assert len(address) == 42

        assert os.path.exists(keystore)
        with open(keystore) as f:
            data = json.load(f)
        assert "address" in data
        assert "crypto" in data
        assert data["address"] == address[2:]  # keystore address omits 0x


def test_load_wallet_decrypts_successfully():
    """load_wallet() with the correct password recovers the key."""
    with tempfile.TemporaryDirectory() as tmp:
        keystore = os.path.join(tmp, "keystore.json")
        password = "correct-horse-battery-staple"

        address = generate_wallet(keystore, password)
        account = load_wallet(keystore, password)

        assert account.address == address


def test_load_wallet_wrong_password_exits():
    """load_wallet() raises SystemExit for an incorrect password."""
    with tempfile.TemporaryDirectory() as tmp:
        keystore = os.path.join(tmp, "keystore.json")
        generate_wallet(keystore, "right-password")

        with pytest.raises(SystemExit):
            load_wallet(keystore, "wrong-password")


def test_import_wallet_creates_valid_keystore():
    """import_wallet() with a known key creates a loadable keystore."""
    with tempfile.TemporaryDirectory() as tmp:
        keystore = os.path.join(tmp, "keystore.json")
        # A well-known development key (do NOT use for real funds)
        priv = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        password = "dev-password"

        address = import_wallet(keystore, priv, password)
        account = load_wallet(keystore, password)

        assert account.address == address
        assert address == "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
