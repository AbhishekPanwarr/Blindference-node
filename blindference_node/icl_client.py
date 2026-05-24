"""Async HTTP client for the Blindference Inference Coordination Layer (ICL)."""

from __future__ import annotations

import asyncio
import json as _json
import time
from typing import Any

import aiohttp
from eth_account.messages import encode_defunct
from eth_account.signers.local import LocalAccount


class ICLClientError(Exception):
    """Raised when an ICL request fails."""


class ICLNodeUnknownError(ICLClientError):
    """Raised when the ICL returns 401/404 for this node, indicating a reset."""


class ICLClient:
    """Async HTTP client for the ICL internal API.

    Every request is authenticated with an EIP‑191 signature over the
    request body (if any) concatenated with the current timestamp.

    Args:
        base_url: ICL API base URL (e.g. ``"https://icl.blindference.xyz"``).
        wallet: An unlocked ``LocalAccount`` used for signing.
    """

    def __init__(self, base_url: str, wallet: LocalAccount) -> None:
        self._base_url = base_url.rstrip("/")
        self._wallet = wallet

    @property
    def address(self) -> str:
        """The checksummed Ethereum address of the connected wallet."""
        return self._wallet.address

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _sign(self, payload: str) -> str:
        message = encode_defunct(text=payload)
        signed = self._wallet.sign_message(message)
        return signed.signature.hex()

    def _auth_headers(self, body_json: str | None = None) -> dict[str, str]:
        ts = str(int(time.time()))
        payload = (body_json or "") + ts
        return {
            "X-Node-Address": self.address,
            "X-Timestamp": ts,
            "X-Signature": "0x" + self._sign(payload),
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        retries: int = 1,
    ) -> dict[str, Any]:
        body_json = _json.dumps(body) if body else None
        url = f"{self._base_url}{path}"

        last_exc: Exception | None = None
        for attempt in range(retries + 1):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.request(
                        method,
                        url,
                        headers=self._auth_headers(body_json),
                        data=body_json,
                    ) as resp:
                        if resp.status < 400:
                            return await resp.json()  # type: ignore[no-any-return]
                        error_text = await resp.text()
                        if resp.status in (401, 404):
                            raise ICLNodeUnknownError(
                                f"ICL {method} {path} returned {resp.status}: {error_text}"
                            )
                        raise ICLClientError(
                            f"ICL {method} {path} returned {resp.status}: {error_text}"
                        )
            except (aiohttp.ClientConnectionError, aiohttp.ServerTimeoutError) as exc:
                last_exc = exc
                if attempt < retries:
                    await asyncio.sleep(1)
        raise ICLClientError(
            f"ICL {method} {path} failed after {retries + 1} attempts"
        ) from last_exc

    # ------------------------------------------------------------------
    # Phase 2 endpoints
    # ------------------------------------------------------------------

    async def get_challenge(self) -> dict[str, Any]:
        """Fetch a fresh attestation challenge nonce.

        ``GET /internal/challenge/{nodeAddress}``

        Returns:
            ``{"challengeId": str, "nonce": str}`` — *nonce* is a hex string.
        """
        return await self._request("GET", f"/internal/challenge/{self.address}")

    async def submit_attestation(
        self,
        backend_type: str,
        quote: bytes,
        runtime_hash: bytes,
        challenge_id: str,
        supported_model_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Submit an attestation quote to the ICL for verification.

        ``POST /internal/attestation/verify``

        Returns:
            ``{"certHash": str, "expiry": int, "tier": int}``
        """
        body: dict[str, Any] = {
            "nodeAddress": self.address,
            "backendType": backend_type,
            "quote": quote.hex(),
            "runtimeHash": runtime_hash.hex(),
            "challengeId": challenge_id,
        }
        if supported_model_ids:
            body["supportedModelIds"] = supported_model_ids
        return await self._request("POST", "/internal/attestation/verify", body)

    # ------------------------------------------------------------------
    # Phase 3 — assignments & task endpoints
    # ------------------------------------------------------------------

    async def get_assignments(self) -> list[dict[str, Any]]:
        """Fetch pending job assignments for this node.

        ``GET /internal/assignments/{nodeAddress}``

        Returns:
            A list of assignment dicts, each containing keys such as
            ``jobId``, ``role``, ``modelId``, ``promptCid``, ``deadline``,
            and ``insuranceOptIn``.  Returns an empty list when there are
            no pending jobs.

        Raises:
            ICLNodeUnknownError: if the ICL responds 401/404, meaning the
            node is no longer known (e.g. ICL was restarted and lost state).
        """
        try:
            result = await self._request(
                "GET", f"/internal/assignments/{self.address}"
            )
        except ICLClientError as exc:
            msg = str(exc)
            if "returned 401" in msg or "returned 404" in msg:
                raise ICLNodeUnknownError(
                    f"Node {self.address} unknown to ICL — needs re-attestation"
                ) from exc
            raise
        return result.get("assignments", [])

    async def claim_task(self, job_id: str) -> dict[str, Any]:
        """Claim a job to prevent races.

        ``POST /internal/task/claim``

        Returns:
            ``{"promptKeyHandle": …, "outputKeyGranted": …, "claimDeadline": …}``
        """
        return await self._request(
            "POST",
            "/internal/task/claim",
            {"jobId": job_id, "nodeAddress": self.address},
        )

    # ------------------------------------------------------------------
    # Phase 4 — result submission
    # ------------------------------------------------------------------

    async def submit_result(
        self,
        job_id: str,
        output_cid: str,
        commitment: bytes,
        encrypted_output_key_high: int | None = None,
        encrypted_output_key_low: int | None = None,
        encrypted_output_key_inputs: dict[str, Any] | None = None,
        output_key_store_tx: str | None = None,
    ) -> dict[str, Any]:
        """Submit leader inference result to the ICL.

        ``POST /internal/task/result``

        Args:
            job_id: The job identifier.
            output_cid: IPFS CID of the encrypted output blob.
            commitment: 32‑byte commitment ``C`` per the whitepaper.
            encrypted_output_key_high: CoFHE handle for the high 128 bits of the output AES key.
            encrypted_output_key_low: CoFHE handle for the low 128 bits of the output AES key.
            encrypted_output_key_inputs: Full encrypted input dicts (with ctHash,
                securityZone, utype, signature) for both halves under keys
                ``"high"`` and ``"low"``.  The ICL uses these to call
                ``PromptKeyStore.storeOutputKey()`` on-chain.
            output_key_store_tx: Transaction hash if the node already stored the
                output key on-chain via ``PromptKeyStore.storeKey``.
        """
        body: dict[str, Any] = {
            "jobId": job_id,
            "output_cid": output_cid,
            "commitment_hash": commitment.hex(),
        }
        if encrypted_output_key_high is not None:
            body["encrypted_output_key_high"] = str(encrypted_output_key_high)
        if encrypted_output_key_low is not None:
            body["encrypted_output_key_low"] = str(encrypted_output_key_low)
        if encrypted_output_key_inputs is not None:
            body["encrypted_output_key_inputs"] = encrypted_output_key_inputs
        if output_key_store_tx:
            body["output_key_store_tx"] = output_key_store_tx
        return await self._request("POST", "/internal/task/result", body)

    async def submit_verification(
        self,
        job_id: str,
        commitment: bytes,
        verdict: str = "CONFIRM",
        confidence: int = 100,
    ) -> dict[str, Any]:
        """Submit verifier verdict to the ICL.

        ``POST /internal/task/verify``

        Args:
            job_id: The job identifier.
            commitment: 32‑byte commitment computed independently.
            verdict: ``"CONFIRM"`` or ``"REJECT"``.
            confidence: 0‑100 confidence score.
        """
        body = {
            "jobId": job_id,
            "verifier_address": self.address,
            "commitment_hash": commitment.hex(),
            "verdict": verdict,
            "confidence": confidence,
        }
        return await self._request("POST", "/internal/task/verify", body)

    # ------------------------------------------------------------------
    # Phase 3 — job status (for verifier CID polling)
    # ------------------------------------------------------------------

    async def get_job_status(self, job_id: str) -> dict[str, Any]:
        """Fetch the current status of a job.

        ``GET /internal/jobs/{jobId}/status``

        Returns:
            ``{"jobId": …, "status": …, "outputCid": …, "leaderCommitment": …}``
        """
        return await self._request("GET", f"/internal/jobs/{job_id}/status")

    # ------------------------------------------------------------------
    # Phase 6 — heartbeat
    # ------------------------------------------------------------------

    async def send_heartbeat(self) -> dict[str, Any]:
        """Send a liveness heartbeat to the ICL.

        ``POST /internal/heartbeat``

        The ICL refreshes the node's ``last_heartbeat`` timestamp so it
        stays eligible for job assignments.
        """
        return await self._request("POST", "/internal/heartbeat", {
            "nodeAddress": self.address,
            "timestamp": str(int(time.time())),
        })
