"""Blindference Node daemon — heartbeat, attestation watchdog, job polling."""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import TYPE_CHECKING

from web3 import Web3

from blindference_node.attestation.mock import MockAttestationBackend
from blindference_node.config import Config, save_config
from blindference_node.crypto import CoFHEClient, get_cofhe_client
from blindference_node.icl_client import ICLClient
from blindference_node.ipfs_client import IPFSClient
from blindference_node.job_handler import handle_job
from blindference_node.registry import update_attestation, update_heartbeat

if TYPE_CHECKING:
    from eth_account.signers.local import LocalAccount

logger = logging.getLogger("blindference-node")


def _setup_logging(config: Config) -> None:
    """Configure a structured logger."""
    handler = logging.StreamHandler()
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-7s] [%(node)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)

    node_short = config.node_address[:10] if config.node_address else "unknown"
    handler.addFilter(
        lambda record, addr=node_short: setattr(record, "node", addr) or True
    )

    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, config.log_level.upper(), logging.INFO))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _sleep_or_shutdown(shutdown: asyncio.Event, seconds: float) -> bool:
    """Sleep for *seconds*, but return early if *shutdown* is set.

    Returns:
        ``True`` if shutdown was signalled, ``False`` if the timeout elapsed.
    """
    try:
        await asyncio.wait_for(shutdown.wait(), timeout=seconds)
        return True
    except asyncio.TimeoutError:
        return False


async def _re_attest(
    icl: ICLClient,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
) -> bool:
    """Automatically re‑attest the node via the ICL.

    Generates a fresh mock attestation quote, submits it to the ICL,
    persists the new certificate, and best‑effort updates the on‑chain
    attestation record.

    Returns:
        ``True`` on success, ``False`` on failure.
    """
    backend = MockAttestationBackend()
    logger.info("Auto‑re‑attesting node …")
    try:
        challenge = await icl.get_challenge()
        nonce_h = challenge.get("nonce", "")
        nonce = bytes.fromhex(nonce_h.replace("0x", "").replace("0X", "")) if nonce_h else b""
        quote = backend.get_quote(nonce)
        result = await icl.submit_attestation(
            backend.backend_type(),
            quote,
            backend.get_runtime_hash(),
            challenge.get("challengeId", ""),
        )
        config.attestation_cert_hash = result.get("certHash", "")
        config.attestation_expiry = result.get("expiry", 0)
        save_config(config)

        # Best‑effort on‑chain update
        try:
            await asyncio.to_thread(
                update_attestation,
                w3,
                config,
                wallet,
                config.attestation_cert_hash,
                config.attestation_expiry,
            )
        except Exception as exc:
            logger.warning("On‑chain attestation update failed: %s", exc)

        logger.info(
            "Attestation renewed — new expiry: %d",
            config.attestation_expiry,
        )
        return True
    except Exception as exc:
        logger.error("Auto‑re‑attestation failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Core coroutines
# ---------------------------------------------------------------------------


async def heartbeat_loop(
    shutdown: asyncio.Event,
    config: Config,
    w3: Web3,
    wallet: LocalAccount,
    icl: ICLClient,
) -> None:
    """Send a heartbeat every 60 seconds (on‑chain + ICL)."""
    while not shutdown.is_set():
        try:
            await asyncio.to_thread(update_heartbeat, w3, config, wallet)
        except Exception as exc:
            logger.warning("On‑chain heartbeat failed: %s", exc)
        try:
            await icl.send_heartbeat()
            logger.debug("ICL heartbeat sent")
        except Exception as exc:
            logger.warning("ICL heartbeat failed: %s", exc)
        if await _sleep_or_shutdown(shutdown, 60):
            return


async def attestation_watchdog(
    shutdown: asyncio.Event,
    config: Config,
    icl: ICLClient,
    wallet: LocalAccount,
    w3: Web3,
) -> None:
    """Re‑attest before the certificate expires.

    Checks every 10 minutes.  If the certificate expires within the next
    6 hours, the watchdog automatically re‑attests via the ICL and
    persists the updated configuration.
    """
    backend = MockAttestationBackend()

    while not shutdown.is_set():
        now = int(time.time())
        remaining = config.attestation_expiry - now
        needs_re_attest = config.attestation_expiry == 0 or remaining < 6 * 3600

        if needs_re_attest:
            logger.info(
                "Cert %s — re‑attesting …",
                "missing" if config.attestation_expiry == 0 else f"expires in {remaining}s",
            )
            await _re_attest(icl, config, wallet, w3)

        if await _sleep_or_shutdown(shutdown, 600):  # 10 minutes
            return


async def assignment_poller(
    shutdown: asyncio.Event,
    config: Config,
    icl: ICLClient,
    w3: Web3,
    wallet: LocalAccount,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
    concurrent_jobs: asyncio.Semaphore,
) -> None:
    """Poll ICL for pending job assignments every 5 seconds.

    Each assignment spawns a ``handle_job`` task, limited to at most
    ``concurrent_jobs`` running at once.
    """
    last_idle_log = 0
    while not shutdown.is_set():
        try:
            assignments = await icl.get_assignments()
            if assignments:
                logger.info("Received %d assignment(s)", len(assignments))
                for job in assignments:
                    if shutdown.is_set():
                        break
                    asyncio.create_task(
                        _job_wrapper(
                            job, config, wallet, w3, icl, ipfs, cofhe, concurrent_jobs
                        )
                    )
            else:
                now_ts = time.monotonic()
                if now_ts - last_idle_log >= 60:
                    logger.info("No assignments for last 60s")
                    last_idle_log = now_ts
        except Exception as exc:
            logger.warning("Assignment poll failed: %s", exc)
        if await _sleep_or_shutdown(shutdown, 5):
            return


async def _job_wrapper(
    job: dict,
    config: Config,
    wallet: LocalAccount,
    w3: Web3,
    icl: ICLClient,
    ipfs: IPFSClient,
    cofhe: CoFHEClient,
    sem: asyncio.Semaphore,
) -> None:
    """Run *handle_job* behind the concurrency semaphore."""
    role = job.get("role", "leader")
    job_id = job.get("jobId", "?")
    logger.info("Spawning %s job %s", role, job_id)
    async with sem:
        await handle_job(job, config, wallet, w3, icl, ipfs, cofhe)


# ---------------------------------------------------------------------------
# Daemon entry point
# ---------------------------------------------------------------------------


async def start_daemon(config: Config, wallet: LocalAccount) -> None:
    """Start the node daemon and run until interrupted.

    Validates that an attestation certificate exists and hasn't expired.
    If the certificate is missing or expired, automatically re‑attests via
    the ICL before starting the worker loops.

    Then starts three concurrent loops:
        - ``heartbeat_loop`` (every 60 s)
        - ``attestation_watchdog`` (every 10 min)
        - ``assignment_poller`` (every 5 s)

    Gracefully shuts down on ``SIGINT`` / ``SIGTERM``.
    """
    _setup_logging(config)

    wallet_key = "0x" + wallet.key.hex()
    w3 = Web3(Web3.HTTPProvider(config.fhenix_rpc))
    icl = ICLClient(config.icl_endpoint, wallet)
    ipfs = IPFSClient(config.ipfs_gateway)
    cofhe = get_cofhe_client(config, wallet_key)
    concurrent_jobs = asyncio.Semaphore(2)

    now = int(time.time())
    cert_missing = config.attestation_expiry == 0
    cert_expired = config.attestation_expiry <= now

    if cert_missing or cert_expired:
        logger.warning(
            "Attestation certificate %s — triggering auto‑re‑attest …",
            "missing" if cert_missing else f"expired {now - config.attestation_expiry}s ago",
        )
        if not await _re_attest(icl, config, wallet, w3):
            logger.error(
                "Auto‑re‑attestation failed. "
                "Ensure the ICL is reachable and run `blindference-node attest` manually."
            )
            return
        now = int(time.time())

    logger.info("Daemon starting …")
    logger.info("  Address : %s", config.node_address)
    logger.info("  Tier    : %d", config.tier)
    logger.info("  Models  : %s", ", ".join(config.supported_model_ids))
    logger.info(
        "  Cert    : expires in %ds",
        config.attestation_expiry - now,
    )

    shutdown = asyncio.Event()

    # Register signal handlers
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown.set)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(heartbeat_loop(shutdown, config, w3, wallet, icl)),
        asyncio.create_task(attestation_watchdog(shutdown, config, icl, wallet, w3)),
        asyncio.create_task(
            assignment_poller(
                shutdown, config, icl, w3, wallet, ipfs, cofhe, concurrent_jobs
            )
        ),
    ]

    await shutdown.wait()
    logger.info("Shutting down …")

    for task in tasks:
        task.cancel()

    await asyncio.gather(*tasks, return_exceptions=True)
    logger.info("Daemon stopped.")
