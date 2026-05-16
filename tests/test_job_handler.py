"""Tests for blindference_node.job_handler."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from eth_account import Account

from blindference_node.config import Config
from blindference_node.crypto import MockCoFHEClient
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient
from blindference_node.job_handler import handle_job


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
        node_address="0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        icl_endpoint="http://localhost:9999",
        ipfs_gateway="https://node.lighthouse.storage",
        tier=0,
        supported_model_ids=["qwen2.5-7b"],
    )


@pytest.fixture
def w3():
    w3 = MagicMock()
    w3.eth.get_transaction_count.return_value = 5
    w3.eth.gas_price = 20_000_000_000
    return w3


@pytest.fixture
def cofhe():
    return MockCoFHEClient(fixed_key=b"\x01" * 32)


@pytest.fixture
def assignment_leader():
    return {
        "jobId": "0xjob-leader",
        "role": "leader",
        "modelId": "qwen2.5-7b",
        "promptCid": "QmPrompt123",
        "deadline": 9999999999,
        "insuranceOptIn": False,
        "userAddress": "0xabC1230000000000000000000000000000000001",
    }


@pytest.fixture
def assignment_verifier():
    return {
        "jobId": "0xjob-verifier",
        "role": "verifier",
        "modelId": "qwen2.5-7b",
        "promptCid": "QmPrompt456",
        "deadline": 9999999999,
        "insuranceOptIn": False,
    }


# ==================================================================
# Leader flow
# ==================================================================


@pytest.mark.asyncio
async def test_handle_job_leader_full_flow(
    config, wallet, w3, cofhe, assignment_leader
):
    """Leader executes full sequence and submits result."""
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)

    # Mock ICL endpoints
    with patch.object(ICLClient, "claim_task", AsyncMock(return_value={})), \
         patch.object(ICLClient, "submit_result", AsyncMock(return_value={})) as mock_submit:

        # Mock IPFS download to return an encrypted prompt blob
        # Create a valid encrypted blob to avoid decryption failure
        from blindference_node.crypto import encrypt_output_blob
        test_prompt = "What is the capital of France?"
        test_blob = encrypt_output_blob(test_prompt, b"\x01" * 32)

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmOutput789")):

            await handle_job(
                assignment_leader, config, wallet, w3, icl, ipfs, cofhe
            )

            mock_submit.assert_called_once()
            call_args = mock_submit.call_args
            assert call_args[0][0] == "0xjob-leader"
            assert call_args[0][1] == "QmOutput789"  # output_cid
            assert len(call_args[0][2]) == 32  # commitment


# ==================================================================
# Verifier flow
# ==================================================================


@pytest.mark.asyncio
async def test_handle_job_verifier_full_flow(
    config, wallet, w3, cofhe, assignment_verifier
):
    """Verifier executes full sequence and submits verification."""
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)

    with patch.object(ICLClient, "claim_task", AsyncMock(return_value={})), \
         patch.object(ICLClient, "submit_verification", AsyncMock(return_value={})) as mock_verify:

        from blindference_node.crypto import encrypt_output_blob
        test_blob = encrypt_output_blob("Test prompt", b"\x01" * 32)

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmOutputABC")):

            await handle_job(
                assignment_verifier, config, wallet, w3, icl, ipfs, cofhe
            )

            mock_verify.assert_called_once()
            call_args = mock_verify.call_args
            assert call_args[0][0] == "0xjob-verifier"
            assert call_args[0][2] == "CONFIRM"  # verdict
            assert call_args[0][3] == 100  # confidence
            assert len(call_args[0][1]) == 32  # commitment


# ==================================================================
# Error recovery
# ==================================================================


@pytest.mark.asyncio
async def test_handle_job_ipfs_download_failure(
    config, wallet, w3, cofhe, assignment_leader
):
    """Job handler does not crash when IPFS download fails."""
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)

    with patch.object(ICLClient, "claim_task", AsyncMock(return_value={})), \
         patch.object(IPFSClient, "download", AsyncMock(side_effect=RuntimeError("IPFS down"))), \
         patch.object(ICLClient, "submit_result", AsyncMock()) as mock_submit:

        # Should not raise
        await handle_job(
            assignment_leader, config, wallet, w3, icl, ipfs, cofhe
        )
        # Submit should NOT be called because download failed
        mock_submit.assert_not_called()


@pytest.mark.asyncio
async def test_handle_job_icl_claim_failure_continues(
    config, wallet, w3, cofhe, assignment_leader
):
    """Claim failure is logged but job continues."""
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)

    with patch.object(ICLClient, "claim_task", AsyncMock(side_effect=RuntimeError("claim failed"))), \
         patch.object(ICLClient, "submit_result", AsyncMock(return_value={})) as mock_submit:

        from blindference_node.crypto import encrypt_output_blob
        test_blob = encrypt_output_blob("test", b"\x01" * 32)

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmOk")):

            await handle_job(
                assignment_leader, config, wallet, w3, icl, ipfs, cofhe
            )
            # Job should still complete — submit_result was called
            mock_submit.assert_called_once()


@pytest.mark.asyncio
async def test_handle_job_leader_zero_user_address(
    config, wallet, w3, cofhe
):
    """Zero-address userAddress logs warning but continues."""
    assignment = {
        "jobId": "0xjob-zero-user",
        "role": "leader",
        "modelId": "qwen2.5-7b",
        "promptCid": "QmTest",
        "deadline": 9999999999,
        "insuranceOptIn": False,
        # no userAddress → defaults to zero
    }
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)

    with patch.object(ICLClient, "claim_task", AsyncMock(return_value={})), \
         patch.object(ICLClient, "submit_result", AsyncMock(return_value={})) as mock_submit:

        from blindference_node.crypto import encrypt_output_blob
        test_blob = encrypt_output_blob("test", b"\x01" * 32)

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmOk")):

            await handle_job(assignment, config, wallet, w3, icl, ipfs, cofhe)
            mock_submit.assert_called_once()
