"""Tests for blindference_node.node_loop."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import web
from web3 import Web3

from blindference_node.crypto import CoFHEClient
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient

from blindference_node.config import Config
from blindference_node.icl_client import ICLClient
from blindference_node.node_loop import (
    assignment_poller,
    attestation_watchdog,
    heartbeat_loop,
)


class _TestCoFHEClient(CoFHEClient):
    """Minimal test double for CoFHE interface."""

    def __init__(self, fixed_key: bytes | None = None) -> None:
        self._key = fixed_key or b"\x01" * 32
        self._counter = 0

    def decrypt(self, ct_handle: int) -> int:
        return int.from_bytes(self._key[:16], "big")

    def encrypt(self, value: int) -> int:
        self._counter += 1
        return 0xDEAD0000 + self._counter


def _wallet():
    from eth_account import Account
    return Account.from_key(
        bytes.fromhex(
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        )
    )


def _config(**overrides) -> Config:
    base = {
        "node_address": "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
        "keystore_path": "/tmp/test-keystore.json",
        "tier": 0,
        "supported_model_ids": ["qwen2.5-7b"],
        "attestation_backend": "mock",
        "icl_endpoint": "http://localhost:9999",
        "rpc_url": "http://localhost:8545",
        "attestation_cert_hash": "0xabcdef",
        "attestation_expiry": int(time.time()) + 86400,  # 24h valid
    }
    base.update(overrides)
    return Config.model_validate(base)


# ==================================================================
# Heartbeat loop
# ==================================================================


@pytest.mark.asyncio
async def test_heartbeat_loop_runs_and_stops():
    """heartbeat_loop sends heartbeat then stops on shutdown signal."""
    config = _config()
    wallet = _wallet()
    w3 = MagicMock(spec=Web3)

    shutdown = asyncio.Event()

    icl = ICLClient(config.icl_endpoint, wallet)
    with patch("blindference_node.node_loop.update_heartbeat") as mock_hb, \
         patch.object(ICLClient, "send_heartbeat", AsyncMock(return_value={})) as mock_icl_hb:
        task = asyncio.create_task(heartbeat_loop(shutdown, config, w3, wallet, icl))

        # Let it fire once
        await asyncio.sleep(0.1)
        shutdown.set()
        await task

        # ICL heartbeat fires every 60s (free REST call)
        assert mock_icl_hb.call_count >= 1
        # On-chain heartbeat only every 10 days, so may not fire in 0.1s


@pytest.mark.asyncio
async def test_heartbeat_loop_handles_errors():
    """heartbeat_loop does not crash when update_heartbeat raises."""
    config = _config()
    wallet = _wallet()
    w3 = MagicMock(spec=Web3)

    shutdown = asyncio.Event()

    icl = ICLClient(config.icl_endpoint, wallet)
    with patch(
        "blindference_node.node_loop.update_heartbeat",
        side_effect=RuntimeError("RPC down"),
    ), patch.object(ICLClient, "send_heartbeat", AsyncMock(return_value={})):
        task = asyncio.create_task(heartbeat_loop(shutdown, config, w3, wallet, icl))
        await asyncio.sleep(0.1)
        shutdown.set()
        await task  # Should not raise


# ==================================================================
# Assignment poller
# ==================================================================


@pytest.mark.asyncio
async def test_assignment_poller_receives_jobs():
    """assignment_poller receives jobs from ICL and does not crash."""
    config = _config()
    wallet = _wallet()
    icl = ICLClient(config.icl_endpoint, wallet)

    fake_jobs = [
        {
            "jobId": "0xjob1",
            "role": "leader",
            "modelId": "qwen2.5-7b",
            "promptCid": "QmTest123",
            "deadline": int(time.time()) + 600,
            "insuranceOptIn": False,
        },
        {
            "jobId": "0xjob2",
            "role": "verifier",
            "modelId": "qwen2.5-7b",
            "promptCid": "QmTest456",
            "deadline": int(time.time()) + 600,
            "insuranceOptIn": True,
        },
    ]

    w3 = MagicMock(spec=Web3)
    ipfs = IPFSClient(config.ipfs_gateway)
    cofhe = _TestCoFHEClient()
    sem = asyncio.Semaphore(2)

    shutdown = asyncio.Event()

    with patch.object(ICLClient, "get_assignments", AsyncMock(return_value=fake_jobs)):
        task = asyncio.create_task(assignment_poller(shutdown, config, icl, w3, wallet, ipfs, cofhe, sem))
        await asyncio.sleep(0.1)
        shutdown.set()
        await task


@pytest.mark.asyncio
async def test_assignment_poller_empty_list():
    """assignment_poller handles empty assignments gracefully."""
    config = _config()
    wallet = _wallet()
    icl = ICLClient(config.icl_endpoint, wallet)

    w3 = MagicMock(spec=Web3)
    ipfs = IPFSClient(config.ipfs_gateway)
    cofhe = _TestCoFHEClient()
    sem = asyncio.Semaphore(2)

    shutdown = asyncio.Event()

    with patch.object(ICLClient, "get_assignments", AsyncMock(return_value=[])):
        task = asyncio.create_task(assignment_poller(shutdown, config, icl, w3, wallet, ipfs, cofhe, sem))
        await asyncio.sleep(0.1)
        shutdown.set()
        await task


@pytest.mark.asyncio
async def test_assignment_poller_handles_network_errors():
    """assignment_poller does not crash on connection errors."""
    config = _config()
    wallet = _wallet()
    icl = ICLClient(config.icl_endpoint, wallet)

    w3 = MagicMock(spec=Web3)
    ipfs = IPFSClient(config.ipfs_gateway)
    cofhe = _TestCoFHEClient()
    sem = asyncio.Semaphore(2)

    shutdown = asyncio.Event()

    with patch.object(
        ICLClient, "get_assignments", AsyncMock(side_effect=ConnectionError("refused"))
    ):
        task = asyncio.create_task(assignment_poller(shutdown, config, icl, w3, wallet, ipfs, cofhe, sem))
        await asyncio.sleep(0.1)
        shutdown.set()
        await task


# ==================================================================
# Attestation watchdog
# ==================================================================


@pytest.mark.asyncio
async def test_attestation_watchdog_triggers_when_near_expiry():
    """attestation_watchdog re-attests when expiry < 6 hours away."""
    config = _config(attestation_expiry=int(time.time()) + 1800)  # 30min
    wallet = _wallet()
    icl = ICLClient(config.icl_endpoint, wallet)
    w3 = MagicMock(spec=Web3)

    shutdown = asyncio.Event()

    fake_challenge = {"challengeId": "c1", "nonce": "deadbeef"}
    fake_result = {"certHash": "0xnewcert", "expiry": int(time.time()) + 86400, "tier": 0}

    with patch.object(
        ICLClient, "get_challenge", AsyncMock(return_value=fake_challenge)
    ), patch.object(
        ICLClient, "submit_attestation", AsyncMock(return_value=fake_result)
    ), patch(
        "blindference_node.node_loop.save_config"
    ), patch(
        "blindference_node.node_loop.update_attestation"
    ):
        task = asyncio.create_task(attestation_watchdog(shutdown, config, icl, wallet, w3))
        await asyncio.sleep(0.3)
        shutdown.set()
        await task

    # Config should have been updated with new cert
    assert config.attestation_cert_hash == "0xnewcert"
    assert config.attestation_expiry > int(time.time()) + 80000


@pytest.mark.asyncio
async def test_attestation_watchdog_skips_when_far_from_expiry():
    """attestation_watchdog does NOT re-attest when expiry is far off."""
    config = _config(attestation_expiry=int(time.time()) + 86400)  # 24h
    wallet = _wallet()
    icl = ICLClient(config.icl_endpoint, wallet)
    w3 = MagicMock(spec=Web3)

    shutdown = asyncio.Event()

    with patch.object(ICLClient, "get_challenge") as mock_challenge:
        task = asyncio.create_task(attestation_watchdog(shutdown, config, icl, wallet, w3))
        await asyncio.sleep(0.3)
        shutdown.set()
        await task

        mock_challenge.assert_not_called()


# ==================================================================
# start_daemon validation
# ==================================================================


def test_start_daemon_rejects_expired_cert():
    """start_daemon exits early when attestation is expired."""
    from blindference_node.node_loop import start_daemon

    config = _config(attestation_expiry=int(time.time()) - 3600)  # 1h expired
    wallet = _wallet()

    asyncio.run(start_daemon(config, wallet))  # Should log error and return, not crash


def test_start_daemon_rejects_no_cert():
    """start_daemon exits early when no attestation exists."""
    from blindference_node.node_loop import start_daemon

    config = _config(attestation_expiry=0)
    wallet = _wallet()

    asyncio.run(start_daemon(config, wallet))  # Should log error and return
