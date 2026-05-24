"""Tests for blindference_node.icl_client."""

import json
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct

from blindference_node.icl_client import ICLClient, ICLClientError


@pytest.fixture
def wallet():
    return Account.from_key(
        bytes.fromhex(
            "ac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"
        )
    )


@pytest.fixture
def icl_client(wallet):
    return ICLClient("http://localhost:9999", wallet)


# ------------------------------------------------------------------
# Helpers to verify signatures
# ------------------------------------------------------------------


def _verify_headers(headers, wallet, expected_body_json):
    """Helper: verify that X-Signature is valid for (body + timestamp)."""
    ts = headers.get("X-Timestamp", "")
    body = expected_body_json or ""
    expected_payload = body + ts
    message = encode_defunct(text=expected_payload)
    addr = wallet.address
    sig = headers.get("X-Signature", "").replace("0x", "")
    recovered = Account.recover_message(message, signature="0x" + sig)
    assert recovered == addr


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_client_address_matches_wallet(wallet, icl_client):
    assert icl_client.address == wallet.address


@pytest.mark.asyncio
async def test_get_challenge_signature(wallet, icl_client):
    """get_challenge sends correctly signed GET request."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"challengeId": "abc", "nonce": "deadbeef"}
        )
        mock_req.return_value.__aenter__.return_value = mock_resp

        await icl_client.get_challenge()

        call_args = mock_req.call_args
        headers = call_args[1].get("headers", {})
        assert headers.get("X-Node-Address") == wallet.address
        _verify_headers(headers, wallet, None)


@pytest.mark.asyncio
async def test_submit_attestation_sends_correct_body(wallet, icl_client):
    """submit_attestation sends the expected JSON body."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={"certHash": "0xabcdef", "expiry": 1234567890, "tier": 0}
        )
        mock_req.return_value.__aenter__.return_value = mock_resp

        quote = b"\x01\x02\x03"
        runtime = b"\xaa" * 32
        result = await icl_client.submit_attestation(
            "mock", quote, runtime, "challenge-1"
        )

        assert result["certHash"] == "0xabcdef"
        assert result["expiry"] == 1234567890
        assert result["tier"] == 0

        call_args = mock_req.call_args
        headers = call_args[1].get("headers", {})
        assert headers.get("X-Node-Address") == wallet.address

        body_json = call_args[1].get("data")
        body = json.loads(body_json)
        assert body["backendType"] == "mock"
        assert body["quote"] == quote.hex()
        assert body["runtimeHash"] == runtime.hex()
        assert body["challengeId"] == "challenge-1"

        _verify_headers(headers, wallet, body_json)


@pytest.mark.asyncio
async def test_http_error_raises_icl_client_error(wallet, icl_client):
    """Non-2xx responses raise ICLClientError."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal server error")
        mock_req.return_value.__aenter__.return_value = mock_resp

        with pytest.raises(ICLClientError, match="returned 500"):
            await icl_client.get_challenge()


@pytest.mark.asyncio
async def test_connection_error_retries_then_raises(wallet, icl_client):
    """Connection errors retry once, then raise ICLClientError."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_req.side_effect = aiohttp.ClientConnectionError("refused")

        with pytest.raises(ICLClientError, match="failed after 2 attempts"):
            await icl_client.get_challenge()

    assert mock_req.call_count == 2  # 1 initial + 1 retry


@pytest.mark.asyncio
async def test_get_assignments_empty(wallet, icl_client):
    """get_assignments returns empty list when no jobs are pending."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"assignments": []})
        mock_req.return_value.__aenter__.return_value = mock_resp

        result = await icl_client.get_assignments()
        assert result == []
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_get_assignments_populated(wallet, icl_client):
    """get_assignments returns job list when ICL has pending work."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(
            return_value={
                "assignments": [
                    {
                        "jobId": "0xabc",
                        "role": "leader",
                        "modelId": "qwen2.5-7b",
                        "promptCid": "QmTest",
                        "deadline": 1234567890,
                        "insuranceOptIn": False,
                    },
                    {
                        "jobId": "0xdef",
                        "role": "verifier",
                        "modelId": "qwen2.5-14b",
                        "promptCid": "QmTest2",
                        "deadline": 1234567899,
                        "insuranceOptIn": True,
                    },
                ]
            }
        )
        mock_req.return_value.__aenter__.return_value = mock_resp

        result = await icl_client.get_assignments()
        assert len(result) == 2
        assert result[0]["jobId"] == "0xabc"
        assert result[0]["role"] == "leader"
        assert result[1]["role"] == "verifier"
        assert result[1]["insuranceOptIn"] is True


# ==================================================================
# Phase 4 — task endpoints
# ==================================================================


@pytest.mark.asyncio
async def test_claim_task(wallet, icl_client):
    """claim_task sends correct POST body."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"claimDeadline": 1234567890})
        mock_req.return_value.__aenter__.return_value = mock_resp

        result = await icl_client.claim_task("0xjob123")
        assert result["claimDeadline"] == 1234567890

        call_args = mock_req.call_args
        body = json.loads(call_args[1].get("data", "{}"))
        assert body["jobId"] == "0xjob123"
        assert body["nodeAddress"] == wallet.address


@pytest.mark.asyncio
async def test_submit_result(wallet, icl_client):
    """submit_result sends the commitment and output CID."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"status": "accepted"})
        mock_req.return_value.__aenter__.return_value = mock_resp

        c = b"\xab" * 32
        result = await icl_client.submit_result(
            "0xjob1", "QmOutputCID", c, "0xhandle1,0xhandle2"
        )
        assert result["status"] == "accepted"

        call_args = mock_req.call_args
        body = json.loads(call_args[1].get("data", "{}"))
        assert body["jobId"] == "0xjob1"
        assert body["output_cid"] == "QmOutputCID"
        assert body["commitment_hash"] == c.hex()
        assert body["encrypted_output_key_high"] == "0xhandle1,0xhandle2"


@pytest.mark.asyncio
async def test_submit_verification(wallet, icl_client):
    """submit_verification sends verdict and confidence."""
    with patch("aiohttp.ClientSession.request") as mock_req:
        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"status": "recorded"})
        mock_req.return_value.__aenter__.return_value = mock_resp

        c = b"\xcd" * 32
        result = await icl_client.submit_verification(
            "0xjob2", c, "CONFIRM", 95
        )
        assert result["status"] == "recorded"

        call_args = mock_req.call_args
        body = json.loads(call_args[1].get("data", "{}"))
        assert body["jobId"] == "0xjob2"
        assert body["verifier_address"] == wallet.address
        assert body["commitment_hash"] == c.hex()
        assert body["verdict"] == "CONFIRM"
        assert body["confidence"] == 95
