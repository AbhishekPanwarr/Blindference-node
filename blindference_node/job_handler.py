"""Job handler — execute an inference job from end to end."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from blindference_node.commitment import compute_commitment
from blindference_node.crypto import (
    CoFHEClient,
    decrypt_prompt_blob,
    encrypt_output_blob,
    format_output_key_handle,
    generate_output_key,
    reconstruct_key,
    split_key_for_cofhe,
)
from blindference_node.execution import run_deterministic_inference
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient
from blindference_node.registry import store_output_key as registry_store_output_key

if TYPE_CHECKING:
    from eth_account.signers.local import LocalAccount
    from web3 import Web3

    from blindference_node.config import Config

logger = logging.getLogger("blindference-node")


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
    try:
        claim = await icl.claim_task(job_id)
        logger.info("Job %s: claimed", job_id)
    except Exception as exc:
        logger.warning("Job %s: claim failed (%s) — continuing", job_id, exc)
        claim = {}

    # 2 — Retrieve & reconstruct prompt key
    kp_high_handle = claim.get("kpHighHandle", 0)
    kp_low_handle = claim.get("kpLowHandle", 0)
    if not kp_high_handle or not kp_low_handle:
        logger.error("Job %s: missing CoFHE key handles — cannot decrypt prompt", job_id)
        return None

    try:
        high_val = cofhe.decrypt(kp_high_handle)
        low_val = cofhe.decrypt(kp_low_handle)
        kp = reconstruct_key(high_val, low_val)
        logger.info("Job %s: prompt key reconstructed (CoFHE)", job_id)
    except Exception as exc:
        logger.error("Job %s: CoFHE decrypt failed: %s", job_id, exc)
        return None

    # 3 — Download encrypted prompt
    blob = await ipfs.download(prompt_cid)

    # 4 — Decrypt prompt
    prompt_text = decrypt_prompt_blob(blob, kp)
    logger.info("Job %s: prompt decrypted (%d chars)", job_id, len(prompt_text))

    # 5 — Run inference
    output_text = run_deterministic_inference(model_id, prompt_text)
    logger.info("Job %s: inference complete (%d chars)", job_id, len(output_text))

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

    try:
        logger.info("Job %s: starting as leader", job_id)

        result = await _common_steps(assignment, icl, ipfs, cofhe)
        if result is None:
            return
        output_text, kp = result

        # 6 — Encrypt output + upload
        ko = generate_output_key()
        output_blob = encrypt_output_blob(output_text, ko)
        output_cid = await ipfs.upload(output_blob)
        logger.info("Job %s: output uploaded → %s", job_id, output_cid)

        # 7 — Compute commitment
        c = compute_commitment(output_cid, output_text)

        # 8 — Store output key + submit result
        if int(user_address, 16) == 0:
            logger.warning(
                "Job %s: userAddress not in assignment — "
                "output key stored to zero address",
                job_id,
            )

        ko_high, ko_low = split_key_for_cofhe(ko)
        try:
            h_high = cofhe.encrypt(ko_high)
            h_low = cofhe.encrypt(ko_low)
            registry_store_output_key(
                w3, config, wallet, job_id, h_high, h_low, user_address,
            )
            output_key_enc = format_output_key_handle(h_high, h_low)
        except Exception as exc:
            logger.warning("Job %s: output-key storage failed: %s", job_id, exc)
            output_key_enc = "0x"

        await icl.submit_result(job_id, output_cid, c, output_key_enc)
        logger.info("Job %s: result submitted (leader)", job_id)

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

    try:
        logger.info("Job %s: starting as verifier", job_id)

        result = await _common_steps(assignment, icl, ipfs, cofhe)
        if result is None:
            return
        output_text, kp = result  # noqa: F841

        # Poll for leader's output CID
        try:
            leader_cid = await _poll_leader_cid(icl, job_id)
            logger.info("Job %s: leader CID received → %s", job_id, leader_cid)
        except asyncio.TimeoutError:
            logger.error("Job %s: leader CID not available — skipping", job_id)
            return

        # Compute commitment using leader's CID + verifier's output text
        c = compute_commitment(leader_cid, output_text)

        await icl.submit_verification(job_id, c, "CONFIRM", 100)
        logger.info("Job %s: verification submitted (verifier)", job_id)

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
    delay = 2.0
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status = await icl.get_job_status(job_id)
        except Exception:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
            continue

        cid = status.get("outputCid")
        if cid and cid != "None":
            return str(cid)

        await asyncio.sleep(delay)
        delay = min(delay * 2, 30)

    raise asyncio.TimeoutError(f"Leader CID not available for job {job_id} after {timeout}s")
