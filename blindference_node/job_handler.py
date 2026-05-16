"""Job handler — execute an inference job from end to end."""

from __future__ import annotations

import logging
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


async def handle_job(
    assignment: dict,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
) -> None:
    """Execute a single inference job from assignment to result submission.

    Sequence:
        1. Claim the task via ICL (returns kpHighHandle / kpLowHandle).
        2. CoFHE‑decrypt both handles → reconstruct the 32‑byte AES prompt key.
        3. Download the encrypted prompt blob from IPFS.
        4. AES‑256‑GCM decrypt the prompt.
        5. Run deterministic inference.
        6. Generate output key, AES‑encrypt output, upload to IPFS.
        7. Compute the commitment hash.
        8. Leader: CoFHE‑encrypt output key halves, store on‑chain, submit result.
           Verifier: submit verification verdict.
    """
    job_id = assignment.get("jobId", "unknown")
    role = assignment.get("role", "leader")
    model_id = assignment.get("modelId", "qwen2.5-7b")
    prompt_cid = assignment.get("promptCid", "")
    user_address = assignment.get(
        "userAddress", "0x0000000000000000000000000000000000000000"
    )

    try:
        logger.info("Job %s: starting (%s, model=%s)", job_id, role, model_id)

        # 1 — Claim task
        try:
            claim = await icl.claim_task(job_id)
            logger.info("Job %s: claimed", job_id)
        except Exception as exc:
            logger.warning("Job %s: claim failed (%s) — continuing", job_id, exc)
            claim = {}

        # 2 — Retrieve & reconstruct prompt key via CoFHE
        kp_high_handle = claim.get("kpHighHandle", 0)
        kp_low_handle = claim.get("kpLowHandle", 0)
        if kp_high_handle and kp_low_handle:
            try:
                high_val = cofhe.decrypt(kp_high_handle)
                low_val = cofhe.decrypt(kp_low_handle)
                kp = reconstruct_key(high_val, low_val)
                logger.info("Job %s: prompt key reconstructed (CoFHE)", job_id)
            except Exception as exc:
                logger.error("Job %s: CoFHE decrypt failed: %s", job_id, exc)
                return
        else:
            mock_val = cofhe.decrypt(0)  # mock: returns fixed uint128
            kp = mock_val.to_bytes(16, "big") * 2  # 32-byte key
            logger.info("Job %s: prompt key from mock", job_id)

        # 3 — Download encrypted prompt
        blob = await ipfs.download(prompt_cid)

        # 4 — Decrypt prompt
        prompt_text = decrypt_prompt_blob(blob, kp)
        logger.info("Job %s: prompt decrypted (%d chars)", job_id, len(prompt_text))

        # 5 — Run inference
        output_text = run_deterministic_inference(model_id, prompt_text)
        logger.info("Job %s: inference complete (%d chars)", job_id, len(output_text))

        # 6 — Encrypt output + upload
        ko = generate_output_key()
        output_blob = encrypt_output_blob(output_text, ko)
        output_cid = await ipfs.upload(output_blob)
        logger.info("Job %s: output uploaded → %s", job_id, output_cid)

        # 7 — Compute commitment
        c = compute_commitment(output_cid, output_text)

        # 8 — Submit to ICL
        if role == "leader":
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
                logger.warning("Job %s: CoFHE encrypt/output-key storage failed: %s", job_id, exc)
                output_key_enc = "0x"

            await icl.submit_result(job_id, output_cid, c, output_key_enc)
            logger.info("Job %s: result submitted (leader)", job_id)
        else:
            await icl.submit_verification(job_id, c, "CONFIRM", 100)
            logger.info("Job %s: verification submitted (verifier)", job_id)

    except Exception as exc:
        logger.error("Job %s: failed — %s", job_id, exc, exc_info=True)
