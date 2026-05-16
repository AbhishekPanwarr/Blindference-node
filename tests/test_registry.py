"""Tests for blindference_node.registry."""

import os
from unittest.mock import MagicMock, patch

import pytest
from eth_account import Account

from blindference_node.config import Config
from blindference_node.registry import (
    _CONTRACTS,
    _to_bytes32,
    get_node_registry,
    register_node,
)


@pytest.fixture
def wallet():
    return Account.from_key(
        bytes.fromhex(
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        )
    )


@pytest.fixture
def config():
    return Config(
        tier=0,
        supported_model_ids=["qwen2.5-7b"],
        zdr_compliant=False,
        network="fhenix_testnet",
    )


@pytest.fixture
def mock_w3():
    w3 = MagicMock()
    w3.eth.get_transaction_count.return_value = 5
    w3.eth.gas_price = 20_000_000_000
    w3.eth.send_raw_transaction.return_value = b"\x01" * 32
    w3.eth.wait_for_transaction_receipt.return_value = MagicMock(
        transactionHash=b"\x02" * 32
    )
    return w3


# ------------------------------------------------------------------
# _to_bytes32
# ------------------------------------------------------------------


def test_to_bytes32_hex_string():
    result = _to_bytes32("0x" + "ab" * 32)
    assert len(result) == 32
    assert result.hex().startswith("ab")


def test_to_bytes32_short_string_pads():
    result = _to_bytes32("hello")
    assert len(result) == 32
    assert result.startswith(b"hello")


def test_to_bytes32_long_string_hashes():
    result = _to_bytes32("a" * 100)
    assert len(result) == 32


# ------------------------------------------------------------------
# node operator registry path
# ------------------------------------------------------------------


def test_register_node_via_operator_registry(mock_w3, config, wallet):
    """When NodeOperatorRegistry is available, use register()."""
    with patch(
        "blindference_node.registry.get_node_operator_registry"
    ) as mock_get_op:
        mock_contract = MagicMock()

        # build_transaction must return a real dict so sign_transaction works
        mock_contract.functions.register.return_value.build_transaction.return_value = {
            "from": wallet.address,
            "to": "0x0000000000000000000000000000000000000000",
            "value": 100_000,
            "nonce": 5,
            "gas": 500_000,
            "gasPrice": 20_000_000_000,
            "chainId": 421614,
            "data": b"",
        }
        mock_get_op.return_value = mock_contract

        tx_hash = register_node(mock_w3, config, wallet, 100_000, "0xcert")

        assert tx_hash is not None
        mock_contract.functions.register.assert_called_once()
        call_args = mock_contract.functions.register.call_args
        assert call_args[0][0] == "0xcert"  # ipfsCID = cert_hash
        assert call_args[0][3] is False     # zdrCompliant
        assert call_args[0][4] == "global"


# ------------------------------------------------------------------
# node attestation registry commit path
# ------------------------------------------------------------------


def test_register_node_via_attestation_commit(mock_w3, config, wallet):
    """When NodeOperatorRegistry unavailable, fallback to attestation commit()."""
    with patch(
        "blindference_node.registry.get_node_operator_registry",
        return_value=None,
    ), patch("blindference_node.registry.get_node_registry") as mock_get_att:
        mock_contract = MagicMock()
        mock_contract.functions.digest.return_value.call.return_value = b"\x03" * 32

        mock_contract.functions.commit.return_value.build_transaction.return_value = {
            "from": wallet.address,
            "to": "0x0000000000000000000000000000000000000000",
            "value": 0,
            "nonce": 5,
            "gas": 300_000,
            "gasPrice": 20_000_000_000,
            "chainId": 421614,
            "data": b"",
        }
        mock_get_att.return_value = mock_contract

        tx_hash = register_node(mock_w3, config, wallet, 100_000, "0x" + "ab" * 32)

        assert tx_hash is not None
        mock_contract.functions.commit.assert_called_once()


def test_register_node_no_contract_returns_none(mock_w3, config, wallet):
    """When no contract is available, return None without error."""
    with patch(
        "blindference_node.registry.get_node_operator_registry",
        return_value=None,
    ), patch(
        "blindference_node.registry.get_node_registry",
        side_effect=ValueError("no address"),
    ):
        result = register_node(mock_w3, config, wallet, 100_000, "0xcert")
        assert result is None


# ------------------------------------------------------------------
# contract addresses
# ------------------------------------------------------------------


def test_testnet_has_addresses():
    testnet = _CONTRACTS.get("fhenix_testnet", {})
    assert "NodeAttestationRegistry" in testnet
    addr = testnet["NodeAttestationRegistry"]
    assert addr.startswith("0x")
    assert int(addr, 16) > 0
