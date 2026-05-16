"""Job handler — execute an inference job from end to end."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from blindference_node.commitment import compute_commitment
from blindference_node.crypto import (
    CoFHEClient,
    decrypt_prompt_blob,
    encrypt_output_blob,
    generate_output_key,
    retrieve_prompt_key,
    store_output_key_for_user,
)
from blindference_node.execution import run_deterministic_inference
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient

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
        1. Claim the task via ICL.
        2. Retrieve the prompt AES key (CoFHE grant).
        3. Download the encrypted prompt blob from IPFS.
        4. Decrypt the prompt.
        5. Run deterministic inference.
        6. Generate output key, encrypt output, upload to IPFS.
        7. Compute the commitment hash.
        8. Submit result (leader) or verification (verifier).
        9. (Leader only) store the output key for the user via CoFHE.

    All exceptions are caught — the daemon keeps running.
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

        # 1 — Claim
        try:
            await icl.claim_task(job_id)
            logger.info("Job %s: claimed", job_id)
        except Exception as exc:
            logger.warning("Job %s: claim failed (%s) — continuing", job_id, exc)

        # 2 — Retrieve prompt key
        kp = retrieve_prompt_key(cofhe, job_id, "permit-placeholder")

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
            ko_handle = store_output_key_for_user(
                cofhe, job_id, ko, user_address
            )
            await icl.submit_result(job_id, output_cid, c, ko_handle)
            logger.info("Job %s: result submitted (leader)", job_id)
        else:
            await icl.submit_verification(job_id, c, "CONFIRM", 100)
            logger.info("Job %s: verification submitted (verifier)", job_id)

    except Exception as exc:
        logger.error("Job %s: failed — %s", job_id, exc, exc_info=True)
