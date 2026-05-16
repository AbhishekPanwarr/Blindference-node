"""Blindference Node CLI — entry point for node operators."""

import asyncio
import os
import sys
import time

import click
from web3 import Web3

from blindference_node import __version__
from blindference_node.attestation.mock import MockAttestationBackend
from blindference_node.config import Config, load_config, save_config
from blindference_node.execution import run_determinism_self_test
from blindference_node.icl_client import ICLClient
from blindference_node.node_loop import start_daemon
from blindference_node.registry import register_node
from blindference_node.utils import detect_gpu
from blindference_node.wallet import generate_wallet, import_wallet, load_wallet

# ---------------------------------------------------------------------------
# Tier / model mapping
# ---------------------------------------------------------------------------

MIN_VRAM_GB = 0.5  # 512 MB

TIER_SPECS = [
    (0, 14.0, ["qwen2.5-7b"]),
    (1, 28.0, ["qwen2.5-7b", "qwen2.5-14b", "qwq-32b"]),
    (2, 65.0, ["qwen2.5-7b", "qwen2.5-14b", "qwq-32b", "llama3.1-70b"]),
]


def _assign_tier(vram_gb: float) -> tuple[int, list[str]]:
    """Map a VRAM amount (GiB) to a tier and supported model list."""
    tier = 0
    models: list[str] = TIER_SPECS[0][2]
    for t, threshold, model_ids in TIER_SPECS:
        if vram_gb >= threshold:
            tier = t
            models = model_ids
    return tier, models


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="blindference-node")
def main() -> None:
    """Blindference Node — register your GPU as a compute provider."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--non-interactive",
    is_flag=True,
    help="Skip all prompts. Requires BLF_PRIVATE_KEY and BLF_KEY_PASSWORD env vars.",
)
def init(non_interactive: bool) -> None:
    """Initialise the node — detect GPU, create wallet, attest, register on-chain."""

    click.echo("=" * 60)
    click.echo("  Blindference Node — Initialisation")
    click.echo(f"  Version {__version__}")
    click.echo("=" * 60)
    click.echo()

    # --- Wallet ---------------------------------------------------------
    keystore_path = os.path.expanduser("~/.blindference/keystore.json")

    if non_interactive:
        private_key = os.environ.get("BLF_PRIVATE_KEY")
        if private_key is None:
            click.echo(
                "Error: --non-interactive requires BLF_PRIVATE_KEY.",
                err=True,
            )
            raise SystemExit(1)
        password = os.environ.get("BLF_KEY_PASSWORD", "")
        if not password:
            click.echo(
                "Warning: BLF_KEY_PASSWORD is empty; keystore will be encrypted "
                "with an empty password.",
            )
        click.echo("Importing wallet from BLF_PRIVATE_KEY ...")
        node_address = import_wallet(keystore_path, private_key, password)
    else:
        choice = click.prompt(
            "Create (n)ew wallet or (i)mport existing private key?",
            type=click.Choice(["n", "i"]),
            default="n",
            show_choices=True,
        )
        if choice == "i":
            private_key_hex = click.prompt(
                "Paste private key (hex)",
                hide_input=True,
                default="",
            )
            if not private_key_hex:
                click.echo("Error: No private key provided.", err=True)
                raise SystemExit(1)
            node_address = import_wallet(keystore_path, private_key_hex)
        else:
            click.echo("Generating new Ethereum wallet ...")
            node_address = generate_wallet(keystore_path)

    click.echo(f"  Node address : {node_address}")

    # --- GPU detection --------------------------------------------------
    click.echo("Detecting GPU ...")
    gpu_name, vram_gb = detect_gpu()
    click.echo(f"  GPU          : {gpu_name}")
    click.echo(f"  VRAM         : {vram_gb:.1f} GiB")

    if vram_gb < MIN_VRAM_GB:
        click.echo(
            f"\nError: Minimum VRAM requirement not met.\n"
            f"  Required: {MIN_VRAM_GB} GiB\n"
            f"  Detected: {vram_gb:.1f} GiB\n"
            f"\nThis node cannot register with the Blindference network.",
            err=True,
        )
        raise SystemExit(1)

    tier, supported_models = _assign_tier(vram_gb)
    click.echo(f"  Tier         : {tier}")
    click.echo(f"  Models       : {', '.join(supported_models)}")

    # --- Determinism self-test ------------------------------------------
    click.echo("Running determinism self-test ...")
    try:
        run_determinism_self_test()
    except RuntimeError as exc:
        click.echo(f"\n{exc}", err=True)
        click.echo(
            "Determinism self-test FAILED. This machine cannot produce "
            "consistent inference output. Registration aborted.",
            err=True,
        )
        raise SystemExit(1)
    click.echo("  Determinism self-test PASSED")

    # --- Attestation ---------------------------------------------------
    click.echo("Running mock attestation ...")
    backend = MockAttestationBackend()
    click.echo(f"  Backend      : {backend.backend_type()}")
    click.echo(f"  Runtime hash : {backend.get_runtime_hash().hex()}")

    # --- ICL communication ---------------------------------------------
    icl_base = os.environ.get("BLF_ICL_ENDPOINT", "https://icl.blindference.xyz")
    click.echo(f"\nConnecting to ICL at {icl_base} ...")

    password = os.environ.get("BLF_KEY_PASSWORD", "")
    wallet_obj = load_wallet(keystore_path, password)
    icl = ICLClient(icl_base, wallet_obj)

    try:
        challenge = asyncio.run(icl.get_challenge())
    except Exception as exc:
        click.echo(f"\nError: Could not reach ICL: {exc}", err=True)
        click.echo(
            "Make sure the ICL is running and accessible. "
            "Use BLF_ICL_ENDPOINT to override the URL.",
            err=True,
        )
        raise SystemExit(1)

    challenge_id = challenge.get("challengeId", "")
    nonce_hex = challenge.get("nonce", "")
    nonce_bytes = bytes.fromhex(nonce_hex) if nonce_hex else b""
    click.echo(f"  Challenge ID : {challenge_id}")

    quote = backend.get_quote(nonce_bytes)
    runtime_hash = backend.get_runtime_hash()
    click.echo(f"  Quote (hex)  : {quote.hex()[:32]}...")

    try:
        attest_result = asyncio.run(
            icl.submit_attestation(
                backend.backend_type(),
                quote,
                runtime_hash,
                challenge_id,
            )
        )
    except Exception as exc:
        click.echo(f"\nError: Attestation submission failed: {exc}", err=True)
        raise SystemExit(1)

    cert_hash = attest_result.get("certHash", "")
    expiry = attest_result.get("expiry", 0)
    icl_tier = attest_result.get("tier", 0)
    click.echo(f"  Cert hash    : {cert_hash}")
    click.echo(f"  Expiry       : {expiry}")
    click.echo(f"  ICL tier     : {icl_tier}")

    final_tier = min(tier, icl_tier)
    click.echo(f"  Final tier   : {final_tier}")

    # --- On-chain registration (best-effort) ---------------------------
    click.echo("\nRegistering on-chain ...")
    stake_wei = 0
    env_stake = os.environ.get("BLF_STAKE_AMOUNT")
    if env_stake is not None:
        stake_wei = int(env_stake)

    if non_interactive:
        if stake_wei == 0:
            click.echo("  Warning: BLF_STAKE_AMOUNT is 0; skipping on-chain registration.")
        else:
            try:
                rpc = os.environ.get("BLF_FHENIX_RPC", "https://testnet.fhenix.zone")
                w3 = Web3(Web3.HTTPProvider(rpc))
                tx_hash = register_node(
                    w3,
                    Config(
                        tier=final_tier,
                        supported_model_ids=supported_models,
                        zdr_compliant=False,
                    ),
                    wallet_obj,
                    stake_wei,
                    cert_hash,
                )
                if tx_hash:
                    click.echo(f"  Registration tx : {tx_hash}")
            except Exception as exc:
                click.echo(f"  Warning: On-chain registration skipped: {exc}")
                click.echo("  The ICL will add your node after a successful attestation.")
    else:
        if not click.confirm(
            "\nRegister on-chain? This requires ETH for gas + stake. "
            f"Stake amount: {stake_wei} wei. Continue?",
            default=True,
        ):
            click.echo("  Skipping on-chain registration.")
        elif stake_wei == 0:
            click.echo("  Stake amount is 0; skipping on-chain registration.")
        else:
            try:
                rpc = os.environ.get("BLF_FHENIX_RPC", "https://testnet.fhenix.zone")
                w3 = Web3(Web3.HTTPProvider(rpc))
                tx_hash = register_node(
                    w3,
                    Config(
                        tier=final_tier,
                        supported_model_ids=supported_models,
                        zdr_compliant=False,
                    ),
                    wallet_obj,
                    stake_wei,
                    cert_hash,
                )
                if tx_hash:
                    click.echo(f"  Registration tx : {tx_hash}")
            except Exception as exc:
                click.echo(f"  Warning: On-chain registration skipped: {exc}")
                click.echo("  The ICL will add your node after a successful attestation.")

    # --- Save config ----------------------------------------------------
    config = Config(
        node_address=node_address,
        keystore_path=keystore_path,
        tier=final_tier,
        supported_model_ids=supported_models,
        attestation_backend="mock",
        attestation_cert_hash=cert_hash,
        attestation_expiry=expiry,
        stake_amount_wei=stake_wei,
    )
    save_config(config)
    click.echo("\nConfiguration saved to ~/.blindference/config.json")

    # --- Summary --------------------------------------------------------
    click.echo()
    click.echo("=" * 60)
    click.echo("  Initialisation complete!")
    click.echo(f"  Address      : {node_address}")
    click.echo(f"  Tier         : {final_tier}")
    click.echo(f"  Models       : {', '.join(supported_models)}")
    click.echo("  Attestation  : mock")
    click.echo(f"  Cert expiry  : {expiry}")
    click.echo("=" * 60)


# ---------------------------------------------------------------------------
# run (stub)
# ---------------------------------------------------------------------------


@main.command()
def run() -> None:
    """Start the node daemon — heartbeat, attestation watchdog, job polling."""
    config = load_config()

    if not config.node_address:
        click.echo(
            "Error: No node configured. Run `blindference-node init` first.",
            err=True,
        )
        raise SystemExit(1)

    if config.attestation_expiry <= int(time.time()):
        click.echo(
            "Error: Attestation certificate expired. "
            "Run `blindference-node attest` to re‑attest.",
            err=True,
        )
        raise SystemExit(1)

    password = os.environ.get("BLF_KEY_PASSWORD")
    if password is None:
        password = click.prompt(
            "Wallet decryption password",
            hide_input=True,
            default="",
            show_default=False,
        )

    wallet = load_wallet(config.keystore_path, password)

    click.echo("=" * 60)
    click.echo("  Blindference Node Daemon")
    click.echo("=" * 60)
    click.echo(f"  Address : {config.node_address}")
    click.echo(f"  Tier    : {config.tier}")
    click.echo(f"  Models  : {', '.join(config.supported_model_ids)}")
    remaining = config.attestation_expiry - int(time.time())
    click.echo(f"  Cert    : expires in {remaining}s")
    click.echo()

    try:
        asyncio.run(start_daemon(config, wallet))
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# status (stub)
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show node status (not yet implemented)."""
    click.echo("`status` is not implemented yet.")


# ---------------------------------------------------------------------------
# attest (stub)
# ---------------------------------------------------------------------------


@main.command()
def attest() -> None:
    """Trigger re-attestation (not yet implemented)."""
    click.echo("`attest` is not implemented yet.")


# ---------------------------------------------------------------------------
# test-determinism
# ---------------------------------------------------------------------------


@main.command("test-determinism")
@click.option("--model", default="facebook/opt-125m", help="Model ID for the determinism test")
@click.option("--prompt", default="Hello, Blindference", help="Prompt to use for the test")
def test_determinism(model: str, prompt: str) -> None:
    """Run real-GPU determinism self‑test — requires vLLM.

    Downloads and loads the specified model, runs the same prompt twice,
    and compares the outputs byte‑for‑byte.
    """
    try:
        from vllm import LLM, SamplingParams
    except (ImportError, ModuleNotFoundError):
        click.echo(
            "Error: This command requires a GPU with vLLM installed.\n"
            "Install GPU dependencies: pip install blindference-node[gpu]",
            err=True,
        )
        raise SystemExit(1)

    click.echo(f"Model:  {model}")
    click.echo(f"Prompt: {prompt}")
    click.echo("Loading model (this may take a moment) …")

    try:
        from blindference_node.execution import run_deterministic_inference
        from blindference_node.execution import run_determinism_self_test

        run_determinism_self_test(model_id=model, test_prompt=prompt)
        click.echo("\nDeterminism self‑test PASSED")
        click.echo("Byte‑identical outputs confirmed.")
    except RuntimeError as exc:
        click.echo(f"\n{exc}", err=True)
        click.echo("Determinism self‑test FAILED", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# withdraw (stub)
# ---------------------------------------------------------------------------


@main.command()
def withdraw() -> None:
    """Initiate stake withdrawal (not yet implemented)."""
    click.echo("`withdraw` is not implemented yet.")
