"""Job handler — execute an inference job from end to end."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from typing import TYPE_CHECKING, Any

from web3 import Web3

from blindference_node.commitment import compute_commitment
from blindference_node.crypto import (
    CoFHEClient,
    decrypt_prompt_blob,
    encrypt_output_blob,
    generate_output_key,
    reconstruct_key,
    split_key_for_cofhe,
)
from blindference_node.execution import run_deterministic_inference
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient

if TYPE_CHECKING:
    from eth_account.signers.local import LocalAccount
    from web3 import Web3

    from blindference_node.config import Config

logger = logging.getLogger("blindference-node")


def _print_job_header(job_id: str, role: str) -> None:
    """Print a visually distinct job start banner to the console."""
    print(f"\n{'━' * 60}")
    print(f"  JOB  {job_id[:20]}…  ROLE: {role.upper()}")
    print(f"{'━' * 60}")


def _print_section(title: str) -> None:
    print(f"\n  ▸ {title}")


def _print_kv(label: str, value: str) -> None:
    print(f"    {label:<22} {value}")


def _print_tx(label: str, tx_hash: str | None) -> None:
    if not tx_hash:
        return
    print(f"    {label:<22} {tx_hash}")
    if tx_hash.startswith("0x"):
        print(f"    {'Explorer':<22} https://sepolia.arbiscan.io/tx/{tx_hash}")


def _print_hash(label: str, value: str | bytes) -> None:
    if isinstance(value, bytes):
        value = value.hex()
    print(f"    {label:<22} {value}")


# ---------------------------------------------------------------------------
# Public dispatcher
# ---------------------------------------------------------------------------


async def handle_job(
    assignment: dict,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
) -> None:
    """Dispatch a job assignment to the appropriate handler by role."""
    role = assignment.get("role", "leader")
    if role == "leader":
        await _do_leader_job(assignment, config, wallet, w3, icl, ipfs, cofhe)
    else:
        await _do_verifier_job(assignment, config, wallet, w3, icl, ipfs, cofhe)


# ---------------------------------------------------------------------------
# Common steps — claim → decrypt → infer (shared by leader & verifier)
# ---------------------------------------------------------------------------


async def _common_steps(
    assignment: dict,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
) -> tuple[str, bytes] | None:
    """Execute steps 1‑5 shared by leader and verifier.

    Returns:
        ``(output_text, key_bytes)`` or ``None`` on unrecoverable failure.
    """
    job_id = assignment.get("jobId", "unknown")
    model_id = assignment.get("modelId", "qwen2.5-7b")
    prompt_cid = assignment.get("promptCid", "")

    # 1 — Claim
    _print_section("Claiming Task from ICL")
    try:
        claim = await icl.claim_task(job_id)
        _print_kv("Status", "Claimed")
    except Exception as exc:
        logger.warning("Job %s: claim failed (%s) — continuing", job_id, exc)
        claim = {}

    # 2 & 3 — Retrieve prompt key AND download encrypted prompt in parallel
    kp_high_handle = claim.get("kpHighHandle", 0)
    kp_low_handle = claim.get("kpLowHandle", 0)
    if not kp_high_handle or not kp_low_handle:
        logger.error("Job %s: missing CoFHE key handles — cannot decrypt prompt", job_id)
        return None

    async def _cofhe_decrypt() -> bytes:
        _print_section("CoFHE Prompt Key Decrypt")
        high_val, low_val, _permit_hash = cofhe.decrypt_prompt_key(kp_high_handle, kp_low_handle)
        _print_kv("Permit hash", _permit_hash)
        return reconstruct_key(high_val, low_val)

    async def _ipfs_download() -> bytes:
        _print_section("Downloading Encrypted Prompt from IPFS")
        data = await ipfs.download(prompt_cid)
        _print_kv("Prompt CID", prompt_cid)
        _print_kv("Size", f"{len(data)} bytes")
        _print_kv("IPFS Gateway", f"https://gateway.pinata.cloud/ipfs/{prompt_cid}")
        return data

    try:
        kp, blob = await asyncio.gather(_cofhe_decrypt(), _ipfs_download())
    except Exception as exc:
        logger.error("Job %s: parallel prompt key decrypt + IPFS download failed: %s", job_id, exc)
        return None

    # 4 — Decrypt prompt
    _print_section("AES-GCM Prompt Decrypt")
    try:
        prompt_text = decrypt_prompt_blob(blob, kp)
        _print_kv("Prompt length", f"{len(prompt_text)} chars")
        # Show first 80 chars for interpretability
        preview = prompt_text[:80].replace("\n", " ")
        _print_kv("Preview", f"{preview}…")
    except Exception as exc:
        logger.error("Job %s: AES-GCM prompt decryption failed: %s", job_id, exc)
        return None

    # 5 — Run inference
    _print_section(f"Inference ({model_id})")
    try:
        output_text = run_deterministic_inference(model_id, prompt_text)
        _print_kv("Output length", f"{len(output_text)} chars")
        preview = output_text[:80].replace("\n", " ")
        _print_kv("Preview", f"{preview}…")
    except Exception as exc:
        logger.error("Job %s: inference execution failed: %s", job_id, exc, exc_info=True)
        return None

    return output_text, kp


# ---------------------------------------------------------------------------
# Leader job
# ---------------------------------------------------------------------------


async def _do_leader_job(
    assignment: dict,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
) -> None:
    """Execute a leader job: infer → upload → store key → submit result."""
    job_id = assignment.get("jobId", "unknown")
    user_address = assignment.get(
        "userAddress", "0x0000000000000000000000000000000000000000"
    )

    _print_job_header(job_id, "leader")

    try:
        result = await _common_steps(assignment, icl, ipfs, cofhe)
        if result is None:
            logger.error("Job %s: common steps failed — aborting leader flow", job_id)
            return
        output_text, kp = result

        # 6 — Encrypt output + upload
        _print_section("Output Encryption & IPFS Upload")
        ko = generate_output_key()
        output_blob = encrypt_output_blob(output_text, ko)
        try:
            output_cid = await ipfs.upload(output_blob)
            _print_kv("Output CID", output_cid)
            _print_kv(
                "IPFS Gateway",
                f"https://gateway.pinata.cloud/ipfs/{output_cid}",
            )
        except Exception as exc:
            logger.error("Job %s: IPFS upload failed: %s", job_id, exc)
            return

        # 7 — Compute commitment
        _print_section("Commitment (SHA-256)")
        c = compute_commitment(output_cid, output_text)
        _print_hash("Commitment", c.hex())
        _print_hash("Input hash", hashlib.sha256(output_text.encode()).hexdigest())

        # 8 — Encrypt output key for user + submit result to ICL
        _print_section("Output Key CoFHE Encryption")
        if int(user_address, 16) == 0:
            logger.warning(
                "Job %s: userAddress not in assignment — output key will be stored to zero address",
                job_id,
            )

        ko_high, ko_low = split_key_for_cofhe(ko)
        encrypted_keys: list[dict[str, Any]] = []
        output_key_store_tx: str | None = None
        try:
            encrypted_keys = cofhe.encrypt_uint128_values([ko_high, ko_low])
            if len(encrypted_keys) >= 2:
                _print_kv("CoFHE high handle", str(encrypted_keys[0]["ctHash"])[:32] + "…")
                _print_kv("CoFHE low handle", str(encrypted_keys[1]["ctHash"])[:32] + "…")
            else:
                logger.warning("Job %s: CoFHE encrypt returned insufficient results", job_id)

            # Store output key on-chain via node bridge (node wallet has ACL)
            prompt_key_store_address = os.environ.get(
                "BLF_PROMPT_KEY_STORE_ADDRESS",
                os.environ.get("PROMPT_KEY_STORE_ADDRESS", ""),
            )
            if prompt_key_store_address and len(encrypted_keys) >= 2:
                output_key_store_job_id = "0x" + Web3.keccak(text=f"{job_id}:output-key").hex()
                output_key_store_tx = cofhe.store_prompt_key(
                    task_id=output_key_store_job_id,
                    prompt_key_store_address=prompt_key_store_address,
                    encrypted_high_input=encrypted_keys[0],
                    encrypted_low_input=encrypted_keys[1],
                    allowed_nodes=[user_address],
                )
                _print_tx("On-chain storage", output_key_store_tx)
        except Exception as exc:
            logger.warning("Job %s: output-key CoFHE encryption or storage failed: %s", job_id, exc)

        _print_section("Submitting Result to ICL")
        try:
            h_high = int(encrypted_keys[0]["ctHash"]) if len(encrypted_keys) >= 2 else None
            h_low = int(encrypted_keys[1]["ctHash"]) if len(encrypted_keys) >= 2 else None
            encrypted_inputs = None
            if encrypted_keys and len(encrypted_keys) >= 2:
                encrypted_inputs = {
                    "high": encrypted_keys[0],
                    "low": encrypted_keys[1],
                }
            await icl.submit_result(
                job_id, output_cid, c,
                encrypted_output_key_high=h_high,
                encrypted_output_key_low=h_low,
                encrypted_output_key_inputs=encrypted_inputs,
                output_key_store_tx=output_key_store_tx,
            )
            _print_kv("Status", "Result submitted to ICL (leader)")
        except Exception as exc:
            logger.error("Job %s: ICL result submission failed: %s", job_id, exc)

    except Exception as exc:
        logger.error("Job %s: leader failed — %s", job_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# Verifier job
# ---------------------------------------------------------------------------


async def _do_verifier_job(
    assignment: dict,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
) -> None:
    """Execute a verifier job: infer → poll leader CID → compute commitment → submit verification."""
    job_id = assignment.get("jobId", "unknown")

    _print_job_header(job_id, "verifier")

    try:
        result = await _common_steps(assignment, icl, ipfs, cofhe)
        if result is None:
            logger.error("Job %s: common steps failed — aborting verifier flow", job_id)
            return
        output_text, kp = result  # noqa: F841

        # Poll for leader's output CID
        _print_section("Polling Leader Output CID")
        try:
            leader_cid = await _poll_leader_cid(icl, job_id)
            _print_kv("Leader CID", leader_cid)
            _print_kv(
                "IPFS Gateway",
                f"https://gateway.pinata.cloud/ipfs/{leader_cid}",
            )
        except asyncio.TimeoutError:
            logger.error("Job %s: leader CID not available — skipping", job_id)
            return

        # Compute commitment using leader's CID + verifier's output text
        _print_section("Verifier Commitment")
        c = compute_commitment(leader_cid, output_text)
        _print_hash("Commitment", c.hex())
        _print_hash("Leader CID hash", hashlib.sha256(leader_cid.encode()).hexdigest())
        _print_hash("Local output hash", hashlib.sha256(output_text.encode()).hexdigest())

        _print_section("Submitting Verification to ICL")
        try:
            await icl.submit_verification(job_id, c, "CONFIRM", 100)
            _print_kv("Status", "Verdict CONFIRM submitted")
        except Exception as exc:
            logger.error("Job %s: ICL verification submission failed: %s", job_id, exc)

    except Exception as exc:
        logger.error("Job %s: verifier failed — %s", job_id, exc, exc_info=True)


# ---------------------------------------------------------------------------
# Leader CID polling
# ---------------------------------------------------------------------------


async def _poll_leader_cid(
    icl: ICLClient, job_id: str, timeout: int = 120
) -> str:
    """Poll ICL for the leader's ``outputCid`` using exponential backoff.

    Raises:
        ``asyncio.TimeoutError`` if the CID is not available within *timeout* seconds.
    """
    delay = 0.5
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = await icl.get_job_status(job_id)
        except Exception as exc:
            logger.debug("Job %s: poll leader CID attempt failed (%s), retrying in %.1fs …", job_id, exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 10.0)
            continue

        cid = status.get("outputCid")
        if cid and cid != "None":
            return str(cid)

        logger.debug("Job %s: leader CID not yet available, retrying in %.1fs …", job_id, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 10.0)

    raise asyncio.TimeoutError(f"Leader CID not available for job {job_id} after {timeout}s")
