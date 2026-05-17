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
    ) -> dict[str, Any]:
        """Submit an attestation quote to the ICL for verification.

        ``POST /internal/attestation/verify``

        Returns:
            ``{"certHash": str, "expiry": int, "tier": int}``
        """
        body = {
            "nodeAddress": self.address,
            "backendType": backend_type,
            "quote": quote.hex(),
            "runtimeHash": runtime_hash.hex(),
            "challengeId": challenge_id,
        }
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
        """
        result = await self._request(
            "GET", f"/internal/assignments/{self.address}"
        )
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
        output_key_enc: str,
    ) -> dict[str, Any]:
        """Submit leader inference result to the ICL.

        ``POST /internal/task/result``

        Args:
            job_id: The job identifier.
            output_cid: IPFS CID of the encrypted output blob.
            commitment: 32‑byte commitment ``C`` per the whitepaper.
            output_key_enc: CoFHE-encrypted output key handle string.
        """
        body = {
            "jobId": job_id,
            "outputCid": output_cid,
            "outputCommitment": commitment.hex(),
            "outputKeyEncrypted": output_key_enc,
        }
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
            "verifierCommitment": commitment.hex(),
            "verdict": verdict,
            "confidenceScore": confidence,
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
