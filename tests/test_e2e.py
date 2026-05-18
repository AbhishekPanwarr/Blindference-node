"""End‑to‑end tests — full node lifecycle with mock ICL server."""

import asyncio
import json
import os
import socket
import tempfile
import time
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web

from blindference_node.attestation.mock import MockAttestationBackend
from blindference_node.config import Config, save_config
from blindference_node.crypto import (
    CoFHEClient,
    encrypt_output_blob,
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
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient
from blindference_node.job_handler import handle_job
from blindference_node.wallet import generate_wallet


# ==================================================================
# Helpers
# ==================================================================


def _find_unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ==================================================================
# Mock ICL server
# ==================================================================


def _create_mock_icl_app() -> web.Application:
    """Build an aiohttp app that simulates all ICL internal endpoints."""
    app = web.Application()
    _received = {"leader_result": None, "verifier_verify": None}

    async def challenge_handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"challengeId": "e2e-challenge-1", "nonce": "deadbeefcafebabe"}
        )

    async def attest_verify_handler(request: web.Request) -> web.Response:
        body = await request.json()
        return web.json_response(
            {
                "certHash": f"0x{body.get('runtimeHash', 'mock')[:10]}",
                "expiry": int(time.time()) + 86400,
                "tier": 0,
            }
        )

    async def assignments_handler(request: web.Request) -> web.Response:
        return web.json_response({"assignments": []})

    async def claim_handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"promptKeyHandle": "0xmock-handle", "claimDeadline": int(time.time()) + 600,
             "kpHighHandle": 0xDEAD0001, "kpLowHandle": 0xDEAD0002}
        )

    async def result_handler(request: web.Request) -> web.Response:
        _received["leader_result"] = await request.json()
        return web.json_response({"status": "accepted"})

    async def verify_handler(request: web.Request) -> web.Response:
        _received["verifier_verify"] = await request.json()
        return web.json_response({"status": "recorded"})

    # Attach received state to app for inspection
    async def job_status_handler(request: web.Request) -> web.Response:
        return web.json_response(
            {"jobId": request.match_info["job_id"], "kpHighHandle": 0xDEAD0001, "kpLowHandle": 0xDEAD0002,
             "status": "running",
             "outputCid": "QmE2EMockLeaderCID",
             "leaderCommitment": None}
        )

    app["received"] = _received

    app.router.add_get(
        "/internal/challenge/{addr}", challenge_handler
    )
    app.router.add_post(
        "/internal/attestation/verify", attest_verify_handler
    )
    app.router.add_get(
        "/internal/assignments/{addr}", assignments_handler
    )
    app.router.add_post("/internal/task/claim", claim_handler)
    app.router.add_post("/internal/task/result", result_handler)
    app.router.add_post("/internal/task/verify", verify_handler)
    app.router.add_get("/internal/jobs/{job_id}/status", job_status_handler)

    return app


@asynccontextmanager
async def _run_mock_icl(port: int):
    """Context manager that starts and stops a mock ICL on *port*."""
    app = _create_mock_icl_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    try:
        yield app
    finally:
        await runner.cleanup()


# ==================================================================
# Fixtures
# ==================================================================


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def wallet(tmp_dir):
    keystore = os.path.join(tmp_dir, "keystore.json")
    addr = generate_wallet(keystore, "test-password")
    return addr, keystore


@pytest.fixture
def config(tmp_dir, wallet):
    addr, keystore = wallet
    return Config(
        node_address=addr,
        keystore_path=keystore,
        tier=0,
        supported_model_ids=["qwen2.5-7b"],
        attestation_backend="mock",
        attestation_cert_hash="0xcert-e2e",
        attestation_expiry=int(time.time()) + 86400,
        icl_endpoint="http://127.0.0.1:{port}",  # filled in test
        ipfs_gateway="https://node.lighthouse.storage",
    )


# ==================================================================
# Leader e2e
# ==================================================================


@pytest.mark.asyncio
async def test_e2e_leader_complete_flow(tmp_dir, wallet, config):
    """Full lifecycle: attest → init config → leader job → submission."""
    port = _find_unused_port()
    config.icl_endpoint = f"http://127.0.0.1:{port}"

    async with _run_mock_icl(port) as app:
        from eth_account import Account
        priv = bytes.fromhex(
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        )
        acct = Account.from_key(priv)

        # --- Step 1: Attestation flow ---
        icl = ICLClient(config.icl_endpoint, acct)
        backend = MockAttestationBackend()

        challenge = await icl.get_challenge()
        nonce = bytes.fromhex(challenge["nonce"])
        quote = backend.get_quote(nonce)
        result = await icl.submit_attestation(
            backend.backend_type(),
            quote,
            backend.get_runtime_hash(),
            challenge["challengeId"],
        )
        config.attestation_cert_hash = result["certHash"]
        config.attestation_expiry = result["expiry"]
        config.tier = result["tier"]
        config.keystore_path = wallet[1]
        config.node_address = acct.address
        save_config(config)

        # --- Step 2: Execute leader job ---
        w3 = _mock_w3()
        ipfs = IPFSClient(config.ipfs_gateway)
        cofhe = _TestCoFHEClient(fixed_key=b"\x01" * 32)

        test_prompt = "What is FHE?"
        test_blob = encrypt_output_blob(test_prompt, b"\x01" * 32)

        from unittest.mock import AsyncMock, patch

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmE2ELeader")):

            await handle_job(
                {
                    "jobId": "0xe2e-leader",
                    "role": "leader",
                    "modelId": "qwen2.5-7b",
                    "promptCid": "QmE2EPrompt",
                    "deadline": int(time.time()) + 600,
                    "insuranceOptIn": False,
                    "userAddress": "0xabC1230000000000000000000000000000000001",
                    "kpHighHandle": 0xDEAD0001,
                    "kpLowHandle": 0xDEAD0002,
                },
                config,
                acct,
                w3,
                icl,
                ipfs,
                cofhe,
            )

        # --- Step 3: Verify ICL received the result ---
        received = app["received"]["leader_result"]
        assert received is not None
        assert received["jobId"] == "0xe2e-leader"
        assert received["outputCid"] == "QmE2ELeader"
        assert "outputCommitment" in received
        assert len(bytes.fromhex(received["outputCommitment"])) == 32
        assert "outputKeyEncrypted" in received


# ==================================================================
# Verifier e2e
# ==================================================================


@pytest.mark.asyncio
async def test_e2e_verifier_complete_flow(tmp_dir, wallet, config):
    """Full lifecycle: attest → init config → verifier job → verification."""
    port = _find_unused_port()
    config.icl_endpoint = f"http://127.0.0.1:{port}"

    async with _run_mock_icl(port) as app:
        from eth_account import Account
        priv = bytes.fromhex(
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        )
        acct = Account.from_key(priv)

        # --- Step 1: Attestation ---
        icl = ICLClient(config.icl_endpoint, acct)
        backend = MockAttestationBackend()

        challenge = await icl.get_challenge()
        nonce = bytes.fromhex(challenge["nonce"])
        quote = backend.get_quote(nonce)
        result = await icl.submit_attestation(
            backend.backend_type(), quote, backend.get_runtime_hash(),
            challenge["challengeId"],
        )
        config.attestation_cert_hash = result["certHash"]
        config.attestation_expiry = result["expiry"]
        config.tier = result["tier"]
        config.keystore_path = wallet[1]
        config.node_address = acct.address
        save_config(config)

        # --- Step 2: Execute verifier job ---
        w3 = _mock_w3()
        ipfs = IPFSClient(config.ipfs_gateway)
        cofhe = _TestCoFHEClient(fixed_key=b"\x01" * 32)

        test_prompt = "Verify this prompt please"
        test_blob = encrypt_output_blob(test_prompt, b"\x01" * 32)

        from unittest.mock import AsyncMock, patch

        with patch.object(IPFSClient, "download", AsyncMock(return_value=test_blob)), \
             patch.object(IPFSClient, "upload", AsyncMock(return_value="QmE2EVerifier")):

            await handle_job(
                {
                    "jobId": "0xe2e-verifier",
                    "role": "verifier",
                    "modelId": "qwen2.5-7b",
                    "promptCid": "QmE2EPrompt2",
                    "deadline": int(time.time()) + 600,
                    "insuranceOptIn": True,
                    "kpHighHandle": 0xDEAD0001,
                    "kpLowHandle": 0xDEAD0002,
                },
                config,
                acct,
                w3,
                icl,
                ipfs,
                cofhe,
            )

        # --- Step 3: Verify ICL received verification ---
        received = app["received"]["verifier_verify"]
        assert received is not None
        assert received["jobId"] == "0xe2e-verifier"
        assert received["verdict"] == "CONFIRM"
        assert received["confidenceScore"] == 100
        assert len(bytes.fromhex(received["verifierCommitment"])) == 32


def _mock_w3():
    from unittest.mock import MagicMock
    w3 = MagicMock()
    w3.eth.get_transaction_count.return_value = 5
    w3.eth.gas_price = 20_000_000_000
    return w3
