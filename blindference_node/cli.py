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
from blindference_node.execution import get_registry, set_registry, run_determinism_self_test
from blindference_node.icl_client import ICLClient
from blindference_node.node_loop import start_daemon
from blindference_node.registry import register_node, get_node_operator_registry, is_node_registered
from blindference_node.utils import detect_gpu
from blindference_node.wallet import generate_wallet, import_wallet, load_wallet

# ---------------------------------------------------------------------------
# Tier / model mapping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# .env file loader — runs before any command
# ---------------------------------------------------------------------------


def _load_env_file() -> None:
    """Load environment variables from .env files if present."""
    import os as _os

    paths = [
        _os.path.join(_os.getcwd(), ".env"),
        _os.path.expanduser("~/.blindference/.env"),
    ]

    try:
        from dotenv import load_dotenv
        for env_path in paths:
            if _os.path.isfile(env_path):
                load_dotenv(env_path, override=False)
        return
    except ImportError:
        pass

    # Fallback simple parser (handles quoted values)
    for env_path in paths:
        if not _os.path.isfile(env_path):
            continue
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, sep, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                # Strip matching single or double quotes (e.g. KEY="val" → KEY=val)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                if key and key not in _os.environ:
                    _os.environ[key] = value


_load_env_file()


MIN_VRAM_GB = 0.5  # 512 MB

# Single small local model for dev / testing — tier 0 (participates in all quorums)
_LOCAL_MODEL = "facebook/opt-125m"  # ~125M params, ~250MB

TIER_SPECS = [
    (0, 0.5, [_LOCAL_MODEL]),   # Any GPU with 0.5GB+ VRAM can run the tiny model
]

# Cloud models available when API keys are present — not gated by VRAM.
_CLOUD_MODELS = {
    "GROQ_API_KEY": ["groq:llama-3.3-70b-versatile"],
    "GOOGLE_API_KEY": ["gemini:gemini-2.5-flash"],
}


def _cloud_models() -> list[str]:
    """Return cloud model IDs for which API keys are present in the environment."""
    models: list[str] = []
    for env_key, model_ids in _CLOUD_MODELS.items():
        if os.environ.get(env_key):
            models.extend(model_ids)
    return models


def _assign_tier(vram_gb: float) -> tuple[int, list[str]]:
    """Map a VRAM amount (GiB) to a tier and supported model list.

    Cloud models (Groq / Gemini) are added regardless of GPU — they run
    remotely and only require the corresponding API key.

    Cloud nodes stay at the GPU-detected tier (0 if no GPU) so they are
    available for the widest set of quorum requests.
    """
    tier = 0
    models: list[str] = list(TIER_SPECS[0][2])  # copy
    for t, threshold, model_ids in TIER_SPECS:
        if vram_gb >= threshold:
            tier = t
            models = list(model_ids)

    cloud = _cloud_models()
    if cloud:
        seen = set(models)
        for m in cloud:
            if m not in seen:
                models.append(m)
                seen.add(m)

    return tier, models


def _check_node_registry_deployed(w3: Web3) -> tuple[bool, str]:
    """Check if a node registry is deployed and return which one.

    Returns (True, "NodeRegistry") if the new contract is deployed,
    (True, "NodeOperatorRegistry") if the legacy one is deployed,
    or (False, "") if none is deployed.
    """
    # Check new NodeRegistry first
    try:
        from blindference_node.registry import get_new_node_registry
        reg = get_new_node_registry(w3)
        if reg is not None:
            reg.functions.isActive("0x" + "0" * 40).call()
            return True, "NodeRegistry"
    except Exception:
        pass

    # Fallback to legacy NodeOperatorRegistry
    try:
        registry = get_node_operator_registry(w3)
        registry.functions.modelExecutorAuthorized(
            "0x" + "0" * 40, "test"
        ).call()
        return True, "NodeOperatorRegistry"
    except Exception:
        pass

    return False, ""


def _estimate_gas_price(w3: Web3) -> int:
    """Return current gas price with a 50% buffer for Arbitrum Sepolia."""
    base = w3.eth.gas_price
    return int(base * 1.5)


def _estimate_register_gas(w3: Web3, address: str, use_new_registry: bool = False) -> int:
    """Estimate gas for NodeRegistry.register() call."""
    try:
        if use_new_registry:
            from blindference_node.registry import get_new_node_registry
            registry = get_new_node_registry(w3)
            if registry is not None:
                tx = registry.functions.register(
                    0,                          # tier
                    "0x" + "0" * 64,            # dummy attestation hash
                    0,                          # attestation expires
                    ["test"],                   # dummy models
                ).build_transaction({
                    "from": address,
                    "value": 0,
                    "nonce": w3.eth.get_transaction_count(address),
                    "gasPrice": _estimate_gas_price(w3),
                })
                return w3.eth.estimate_gas(tx)

        # Fallback to legacy NodeOperatorRegistry
        registry = get_node_operator_registry(w3)
        tx = registry.functions.register(
            "0x" + "0" * 64,  # dummy cert hash
            [0],               # dummy model tiers
            "unknown",         # location
            False,             # zdr_compliant
            "global",          # jurisdiction
        ).build_transaction({
            "from": address,
            "value": 0,
            "nonce": w3.eth.get_transaction_count(address),
            "gasPrice": _estimate_gas_price(w3),
        })
        return w3.eth.estimate_gas(tx)
    except Exception:
        # Fallback estimate
        return 500_000


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.version_option(version=__version__, prog_name="blindference-node")
def main() -> None:
    """Blindference Node — confidential inference on Arbitrum Sepolia."""


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@main.command()
def init() -> None:
    """Initialise the node — create wallet, detect GPU, save config.

    Environment variables used (all optional, falls back to prompts):
        BLF_PRIVATE_KEY     — hex private key to import (if absent, prompts)
        BLF_KEY_PASSWORD      — keystore password (if absent, prompts)
        GROQ_API_KEY          — enables Groq cloud backend
        GOOGLE_API_KEY        — enables Gemini cloud backend
    """

    click.echo("=" * 60)
    click.echo("  Blindference Node — Initialisation")
    click.echo(f"  Version {__version__}")
    click.echo("=" * 60)
    click.echo()

    # --- Wallet ---------------------------------------------------------
    keystore_path = os.path.expanduser("~/.blindference/keystore.json")

    env_key = os.environ.get("BLF_PRIVATE_KEY")
    env_password = os.environ.get("BLF_KEY_PASSWORD")

    if env_key:
        click.echo("  → BLF_PRIVATE_KEY found in environment, importing wallet …")
        password = env_password or ""
        if not env_password:
            click.echo("  → Warning: BLF_KEY_PASSWORD not set; keystore encrypted with empty password.")
        node_address = import_wallet(keystore_path, env_key, password)
    else:
        choice = click.prompt(
            "Create (n)ew wallet or (i)mport existing private key?",
            type=click.Choice(["n", "i"]),
            default="n",
            show_choices=True,
        )
        if choice == "i":
            private_key_hex = click.prompt("Paste private key (hex)", hide_input=True, default="")
            if not private_key_hex:
                click.echo("Error: No private key provided.", err=True)
                raise SystemExit(1)
            node_address = import_wallet(keystore_path, private_key_hex)
        else:
            click.echo("Generating new Ethereum wallet …")
            node_address = generate_wallet(keystore_path)

    click.echo(f"  Node address : {node_address}")

    # --- GPU detection --------------------------------------------------
    click.echo("Detecting GPU ...")
    gpu_name, vram_gb = detect_gpu()
    click.echo(f"  GPU          : {gpu_name}")
    click.echo(f"  VRAM         : {vram_gb:.1f} GiB")

    tier, supported_models = _assign_tier(vram_gb)
    click.echo(f"  Tier         : {tier}")
    click.echo(f"  Models       : {', '.join(supported_models)}")

    # --- Cloud API status -----------------------------------------------
    groq_key = os.environ.get("GROQ_API_KEY")
    google_key = os.environ.get("GOOGLE_API_KEY")
    if groq_key or google_key:
        click.echo(f"\n  Cloud API keys detected:")
        click.echo(f"    • Groq   : {'✓' if groq_key else '✗'}")
        click.echo(f"    • Gemini : {'✓' if google_key else '✗'}")
    else:
        click.echo("\n  NOTE: No GPU detected or insufficient VRAM, and no cloud API keys set.")
        click.echo("  This node can still participate via cloud API inference:")
        click.echo("    • Groq   — set GROQ_API_KEY  in ~/.blindference/.env")
        click.echo("    • Gemini — set GOOGLE_API_KEY in ~/.blindference/.env")
        click.echo("  Add one or both keys, then run `blindference-node run`.")

    # --- Determinism self-test ------------------------------------------
    click.echo("\nRunning determinism self-test ...")
    try:
        run_determinism_self_test()
    except RuntimeError as exc:
        click.echo(f"\n{exc}", err=True)
        click.echo(
            "Determinism self-test FAILED. This machine cannot produce consistent inference output.",
            err=True,
        )
        raise SystemExit(1)
    click.echo("  Determinism self-test PASSED")

    # --- Save config (no attestation yet) -------------------------------
    config = Config(
        node_address=node_address,
        keystore_path=keystore_path,
        tier=tier,
        supported_model_ids=supported_models,
    )
    save_config(config)
    click.echo("\nConfiguration saved to ~/.blindference/config.json")

    # --- Summary --------------------------------------------------------
    click.echo()
    click.echo("=" * 60)
    click.echo("  Initialisation complete!")
    click.echo(f"  Address      : {node_address}")
    click.echo(f"  Tier         : {tier}")
    click.echo(f"  Models       : {', '.join(supported_models)}")
    click.echo()
    click.echo("  NEXT STEPS")
    click.echo("  ──────────────────────────────────────────────────────────")
    click.echo("  1. Set cloud API keys (if no GPU):")
    click.echo("     echo 'GROQ_API_KEY=gsk_...' > ~/.blindference/.env")
    click.echo("     echo 'GOOGLE_API_KEY=AI...' >> ~/.blindference/.env")
    click.echo()
    click.echo("  2. Run attestation:")
    click.echo("     blindference-node attest")
    click.echo()
    click.echo("  3. Start the node:")
    click.echo("     blindference-node run")
    click.echo("=" * 60)


# ---------------------------------------------------------------------------
# attest
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--mock",
    is_flag=True,
    default=False,
    help="Use mock attestation (development). Overrides any hardware TEE path.",
)
@click.option(
    "--tee-key",
    default=None,
    help="Development attestation key (for development TEE simulation).",
)
def attest(mock: bool, tee_key: str | None) -> None:
    """Attest the node with the ICL (TEE / mock).

    Environment variables used (all optional, falls back to prompts):
        BLF_KEY_PASSWORD        — keystore password (if absent, prompts)
        MOCK_ATTESTATION_KEY    — mock attestation quote key (default: weloveblindference)
        BLF_ICL_ENDPOINT        — ICL base URL (default: https://icl.blindference.xyz)
        BLF_RPC_URL             — Arbitrum Sepolia RPC endpoint (preferred)
        BLF_FHENIX_RPC          — Legacy alias for EVM RPC endpoint
    """

    config = load_config()
    if not config.node_address:
        click.echo("Error: No node configured. Run `blindference-node init` first.", err=True)
        raise SystemExit(1)

    click.echo("=" * 60)
    click.echo("  Blindference Node — Attestation")
    click.echo("=" * 60)
    click.echo()

    click.echo(f"  Node address : {config.node_address}")

    # ── Determine attestation type ─────────────────────────────────────
    if mock:
        attestation_type = "mock"
        click.echo("  Attestation  : mock (development — --mock flag)")
    else:
        choice = click.prompt(
            "  Attestation type:\n"
            "    [1] Mock (development)\n"
            "    [2] TEE / TPM (production)\n"
            "  Select",
            type=click.Choice(["1", "2"]),
            default="1",
        )
        if choice == "2":
            click.echo("  TEE / TPM attestation requires hardware support (SGX / TDX / Nitro).")
            click.echo("  For development, you can simulate a TEE with a pre-shared key.")
            use_dev_tee = click.confirm("  Use development TEE simulation?", default=True)
            if not use_dev_tee:
                click.echo("  Production TEE attestation is not yet implemented.")
                click.echo("  Run with --mock for development attestation.")
                raise SystemExit(1)
            attestation_type = "development-tee"
            click.echo("  Attestation  : development TEE simulation")
        else:
            attestation_type = "mock"
            click.echo("  Attestation  : mock (development)")

    # ── Load wallet ────────────────────────────────────────────────────
    password = os.environ.get("BLF_KEY_PASSWORD")
    if password is None:
        password = click.prompt("Wallet decryption password", hide_input=True, default="")
    if not password:
        click.echo("Warning: BLF_KEY_PASSWORD not set; using empty password.")

    wallet_obj = load_wallet(config.keystore_path, password)

    # ── Connect to ICL ───────────────────────────────────────────────
    icl_base = os.environ.get("BLF_ICL_ENDPOINT", "https://icl.blindference.xyz")
    click.echo(f"Connecting to ICL at {icl_base} …")
    icl = ICLClient(icl_base, wallet_obj)

    try:
        challenge = asyncio.run(icl.get_challenge())
    except Exception as exc:
        click.echo(f"\nError: Could not reach ICL: {exc}", err=True)
        raise SystemExit(1)

    challenge_id = challenge.get("challengeId", "")
    nonce_hex = challenge.get("nonce", "")
    nonce_bytes = bytes.fromhex(nonce_hex.replace("0x", "").replace("0X", "")) if nonce_hex else b""
    click.echo(f"  Challenge ID : {challenge_id}")

    # ── Generate attestation quote ─────────────────────────────────────
    backend = MockAttestationBackend()
    mock_key = tee_key or os.environ.get("MOCK_ATTESTATION_KEY", "weloveblindference")
    click.echo(f"  Mock key     : {mock_key}")
    quote = backend.get_quote(nonce_bytes)
    runtime_hash = backend.get_runtime_hash()
    click.echo(f"  Quote (hex)  : {quote.hex()[:32]}…")
    click.echo(f"  Runtime hash : {runtime_hash.hex()}")

    try:
        attest_result = asyncio.run(
            icl.submit_attestation(
                backend.backend_type(),
                quote,
                runtime_hash,
                challenge_id,
                supported_model_ids=config.supported_model_ids,
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

    final_tier = min(config.tier, icl_tier)
    click.echo(f"  Final tier   : {final_tier}")

    # ── On-chain registration (auto-detect, interactive fallback) ───
    click.echo("\nOn-chain Registration")
    click.echo("-" * 60)

    # NodeRegistry lives on Arbitrum Sepolia (chain 421614), not Fhenix testnet.
    # Prefer BLF_RPC_URL (Arbitrum Sepolia Alchemy key) and fall back to legacy
    # BLF_FHENIX_RPC for backwards compatibility.
    rpc = os.environ.get("BLF_RPC_URL") or os.environ.get(
        "BLF_FHENIX_RPC", "https://testnet.fhenix.zone"
    )
    w3 = Web3(Web3.HTTPProvider(rpc))
    registry_deployed, registry_name = _check_node_registry_deployed(w3)

    if not registry_deployed:
        click.echo("  NodeRegistry not deployed on this network.")
        click.echo("  Skipping on-chain registration.")
        click.echo("  The ICL will add your node after successful attestation.")
        config.registered_on_chain = False
    else:
        click.echo(f"  Registry     : {registry_name} deployed")

        # Auto-detect existing registration
        registered, active = is_node_registered(w3, wallet_obj.address)

        if registered and active:
            click.echo(f"  Status       : Already registered and active")
            click.echo(f"  Address      : {wallet_obj.address}")
            click.echo("  Skipping registration transaction.")
            config.registered_on_chain = True
        elif registered and not active:
            click.echo(f"  Status       : Registered but INACTIVE")
            click.echo(f"  Reason       : Attestation expired or heartbeat missed")
            click.echo("  Run `blindference-node run` to send heartbeat and re-activate.")
            config.registered_on_chain = True
        else:
            # Not registered — proceed with interactive registration
            click.echo("  Status       : Not registered")
            if click.confirm("  Register node on-chain? (requires gas for tx)", default=True):
                try:
                    gas_estimate = _estimate_register_gas(
                        w3, wallet_obj.address, use_new_registry=(registry_name == "NodeRegistry")
                    )
                    gas_price = _estimate_gas_price(w3)
                    gas_cost_wei = gas_estimate * gas_price
                    gas_cost_eth = w3.from_wei(gas_cost_wei, "ether")

                    click.echo(f"  Gas estimate : {gas_estimate:,} units")
                    click.echo(f"  Gas price    : {w3.from_wei(gas_price, 'gwei'):.2f} gwei")
                    click.echo(f"  Est. cost    : {gas_cost_eth:.6f} ETH")

                    if click.confirm("  Send registration transaction?", default=True):
                        tx_hash = register_node(
                            w3,
                            Config(
                                tier=final_tier,
                                supported_model_ids=config.supported_model_ids,
                                zdr_compliant=False,
                            ),
                            wallet_obj,
                            0,
                            cert_hash,
                            attestation_expiry=expiry,
                        )
                        if tx_hash:
                            click.echo(f"  Registration tx : {tx_hash}")
                            click.echo(f"  Explorer        : https://sepolia.arbiscan.io/tx/{tx_hash}")
                            config.registered_on_chain = True
                        else:
                            click.echo("  Registration failed (no tx hash returned).")
                            config.registered_on_chain = False
                    else:
                        click.echo("  Registration cancelled by user.")
                        config.registered_on_chain = False
                except Exception as exc:
                    click.echo(f"  Warning: On-chain registration failed: {exc}")
                    click.echo("  The ICL will still add your node after attestation.")
                    config.registered_on_chain = False
            else:
                click.echo("  Skipping on-chain registration.")
                click.echo("  The ICL will add your node after successful attestation.")
                config.registered_on_chain = False

    click.echo("-" * 60)

    # Save updated config
    config.attestation_backend = attestation_type
    config.attestation_cert_hash = cert_hash
    config.attestation_expiry = expiry
    config.tier = final_tier
    save_config(config)
    click.echo("\nAttestation saved to ~/.blindference/config.json")

    click.echo()
    click.echo("=" * 60)
    click.echo("  Attestation complete!")
    click.echo(f"  Type         : {attestation_type}")
    click.echo(f"  Cert hash    : {cert_hash}")
    click.echo(f"  Expires      : {expiry} (Unix)")
    click.echo("=" * 60)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--log-level",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    default=None,
    help="Override the logging level (env: BLF_LOG_LEVEL).",
)
def run(log_level: str | None) -> None:
    """Start the node daemon — heartbeat, attestation watchdog, job polling."""
    config = load_config()
    if log_level is not None:
        config.log_level = log_level.upper()

    if not config.node_address:
        click.echo("Error: No node configured. Run `blindference-node init` first.", err=True)
        raise SystemExit(1)

    if config.attestation_expiry == 0:
        click.echo(
            "Error: No attestation found. Run `blindference-node attest` first.",
            err=True,
        )
        raise SystemExit(1)

    if config.attestation_expiry <= int(time.time()):
        click.echo(
            "Warning: Attestation certificate expired. "
            "Run `blindference-node attest` to re-attest.",
            err=True,
        )
        # Allow continuing — start_daemon will auto-re-attest if ICL is reachable

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

    # Cloud API key check
    groq_key = os.environ.get("GROQ_API_KEY")
    google_key = os.environ.get("GOOGLE_API_KEY")
    if groq_key or google_key:
        click.echo(f"  Cloud   : Groq={'✓' if groq_key else '✗'}  Gemini={'✓' if google_key else '✗'}")
    else:
        click.echo("  Cloud   : no API keys set — will use deterministic mock fallback")
        click.echo("           Set GROQ_API_KEY or GOOGLE_API_KEY for real inference.")
    click.echo()

    # Pre-build registry so custom backends are loaded before jobs arrive.
    set_registry(config)

    try:
        asyncio.run(start_daemon(config, wallet))
    except KeyboardInterrupt:
        pass


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------


@main.command()
def status() -> None:
    """Show node status and configuration summary."""
    config = load_config()
    if not config.node_address:
        click.echo("Node not initialised. Run `blindference-node init` first.")
        raise SystemExit(1)

    now = int(time.time())
    remaining = config.attestation_expiry - now

    click.echo("=" * 60)
    click.echo("  Node Status")
    click.echo("=" * 60)
    click.echo(f"  Address        : {config.node_address}")
    click.echo(f"  Tier           : {config.tier}")
    click.echo(f"  Models         : {', '.join(config.supported_model_ids)}")
    click.echo(f"  Attestation    : {config.attestation_backend or 'none'}")
    click.echo(f"  Cert expiry    : {config.attestation_expiry} ({remaining}s remaining)")
    click.echo(f"  ICL endpoint   : {config.icl_endpoint}")
    click.echo(f"  Fhenix RPC     : {config.fhenix_rpc}")
    click.echo(f"  IPFS gateway   : {config.ipfs_gateway}")
    click.echo(f"  Stake (wei)    : {config.stake_amount_wei}")
    click.echo(f"  CoFHE mode     : {config.cofhe_mode}")
    click.echo("=" * 60)


# ---------------------------------------------------------------------------
# test-determinism
# ---------------------------------------------------------------------------


@main.command("test-determinism")
@click.option("--model", default="facebook/opt-125m", help="Model ID for the determinism test")
@click.option("--prompt", default="Hello, Blindference", help="Prompt to use for the test")
def test_determinism(model: str, prompt: str) -> None:
    """Run determinism self-test — tries vLLM then cloud APIs."""
    click.echo(f"Model:  {model}")
    click.echo(f"Prompt: {prompt}")

    try:
        run_determinism_self_test(model_id=model, test_prompt=prompt)
        click.echo("\nDeterminism self-test PASSED")
        click.echo("Byte-identical outputs confirmed.")
    except RuntimeError as exc:
        click.echo(f"\n{exc}", err=True)
        click.echo("Determinism self-test FAILED", err=True)
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# models
# ---------------------------------------------------------------------------


@main.group("models")
def models_group() -> None:
    """Introspect and test the inference backends."""


@models_group.command("list")
def models_list() -> None:
    """List registered backends and their availability / supported models."""
    config = load_config()
    registry = get_registry(config)

    click.echo("Registered inference backends")
    click.echo("-" * 60)

    rows = registry.status_table()
    if not rows:
        click.echo("  (none)")
        return

    # Simple formatting — columns are short enough
    for row in rows:
        avail = row["available"]
        click.echo(
            f"  [{avail}]  {row['backend']:<12}  {row['models']}"
        )

    click.echo("-" * 60)
    available = registry.available_models()
    click.echo(f"Currently available models: {', '.join(available) if available else '(none)'}")
    if config.custom_backends:
        click.echo(f"Custom backend paths: {', '.join(config.custom_backends)}")


@models_group.command("test")
@click.option("--backend", default="", help="Only test a specific backend name (e.g. 'groq', 'mock')")
@click.option("--model", default="qwen2.5-7b", help="Model ID to use for the test")
@click.option("--prompt", default="Hello, Blindference", help="Prompt to use for the test")
def models_test(backend: str, model: str, prompt: str) -> None:
    """Run a quick inference test against one or all available backends."""
    config = load_config()
    registry = get_registry(config)

    for be in registry._backends.values():
        if backend and be.name() != backend:
            continue
        click.echo(f"\n  Backend: {be.name()}")
        click.echo(f"  Available: {'yes' if be.is_available() else 'no'}")
        if not be.is_available():
            continue
        try:
            result = be.run(model, prompt)
            click.echo(f"  Result: {result[:120]}…" if len(result) > 120 else f"  Result: {result}")
        except Exception as exc:
            click.echo(f"  ERROR: {exc}", err=True)


@models_group.command("add")
@click.argument("dotted_path")
def models_add(dotted_path: str) -> None:
    """Register a custom backend class from a dotted Python path.

    The path must be importable, e.g.

        blindference-node models add my_package.backends:MyBackend

    The class must inherit ``ModelBackend`` and implement the four abstract
    methods.  The path is persisted in ``~/.blindference/config.json``
    (``custom_backends`` list) and loaded automatically on the next
    ``blindference-node run``.
    """
    config = load_config()
    if dotted_path in config.custom_backends:
        click.echo(f"'{dotted_path}' is already registered.")
        return

    # Validate import before saving
    try:
        from blindference_node.backend_loader import _load_from_dotted_path
        backend = _load_from_dotted_path(dotted_path)
        click.echo(f"  Loaded '{backend.name()}' successfully")
    except Exception as exc:
        click.echo(f"Error: Could not import '{dotted_path}': {exc}", err=True)
        raise SystemExit(1)

    config.custom_backends.append(dotted_path)
    save_config(config)
    click.echo(f"Added '{dotted_path}' to custom_backends.")
    click.echo("Run `blindference-node models list` to verify, then `blindference-node run` to activate.")


# ---------------------------------------------------------------------------
# staking
# ---------------------------------------------------------------------------


@main.group("staking")
def staking_group() -> None:
    """BLIND token staking — stake, unstake, and check status."""


@staking_group.command("stake")
@click.argument("amount", type=float)
def staking_stake(amount: float) -> None:
    """Stake BLIND tokens (e.g. 1000)."""
    from blindference_node.registry import (
        approve_blind,
        get_stake_info,
        get_staking_contract,
        stake_blind,
    )

    config = load_config()
    password = os.environ.get("BLF_KEY_PASSWORD")
    if password is None:
        password = click.prompt("Wallet decryption password", hide_input=True, default="")
    wallet = load_wallet(config.keystore_path, password)

    rpc = os.environ.get("BLF_RPC_URL") or os.environ.get("BLF_FHENIX_RPC")
    if not rpc:
        click.echo("Error: BLF_RPC_URL not set.", err=True)
        raise SystemExit(1)

    w3 = Web3(Web3.HTTPProvider(rpc))
    amount_wei = int(amount * 10 ** 18)

    click.echo(f"Staking {amount} BLIND ({amount_wei} wei) …")

    # Check current stake
    info = get_stake_info(w3, wallet.address)
    if info and info["staked"] > 0:
        click.echo(f"  Already staked: {info['staked'] / 10 ** 18} BLIND")
        if not click.confirm("  Add to existing stake?", default=True):
            raise SystemExit(0)

    # Approve
    click.echo("  Approving BLIND transfer …")
    approve_tx = approve_blind(w3, wallet, amount_wei)
    if not approve_tx:
        click.echo("Approve failed.", err=True)
        raise SystemExit(1)

    # Stake
    click.echo("  Staking …")
    stake_tx = stake_blind(w3, wallet, amount_wei)
    if stake_tx:
        click.echo(f"  Staked successfully: {stake_tx}")
        info = get_stake_info(w3, wallet.address)
        if info:
            click.echo(f"  Total staked: {info['staked'] / 10 ** 18} BLIND")
    else:
        click.echo("Stake failed.", err=True)
        raise SystemExit(1)


@staking_group.command("unstake")
def staking_unstake() -> None:
    """Initiate unstake (starts 96h unbonding)."""
    from blindference_node.registry import get_stake_info, initiate_unstake

    config = load_config()
    password = os.environ.get("BLF_KEY_PASSWORD")
    if password is None:
        password = click.prompt("Wallet decryption password", hide_input=True, default="")
    wallet = load_wallet(config.keystore_path, password)

    rpc = os.environ.get("BLF_RPC_URL") or os.environ.get("BLF_FHENIX_RPC")
    if not rpc:
        click.echo("Error: BLF_RPC_URL not set.", err=True)
        raise SystemExit(1)

    w3 = Web3(Web3.HTTPProvider(rpc))
    info = get_stake_info(w3, wallet.address)
    if not info or info["staked"] == 0:
        click.echo("No active stake found.")
        return

    click.echo(f"Initiating unstake of {info['staked'] / 10 ** 18} BLIND …")
    tx = initiate_unstake(w3, wallet)
    if tx:
        click.echo(f"  Unstake initiated: {tx}")
        click.echo(f"  Available to withdraw after: {info['unbondingAvailableAt']} (96 hours)")
    else:
        click.echo("Unstake initiation failed.", err=True)
        raise SystemExit(1)


@staking_group.command("withdraw")
def staking_withdraw() -> None:
    """Complete unstake after unbonding period."""
    from blindference_node.registry import complete_unstake, get_stake_info

    config = load_config()
    password = os.environ.get("BLF_KEY_PASSWORD")
    if password is None:
        password = click.prompt("Wallet decryption password", hide_input=True, default="")
    wallet = load_wallet(config.keystore_path, password)

    rpc = os.environ.get("BLF_RPC_URL") or os.environ.get("BLF_FHENIX_RPC")
    if not rpc:
        click.echo("Error: BLF_RPC_URL not set.", err=True)
        raise SystemExit(1)

    w3 = Web3(Web3.HTTPProvider(rpc))
    info = get_stake_info(w3, wallet.address)
    if not info or info["unbonding"] == 0:
        click.echo("No unbonding stake found.")
        return

    now = w3.eth.get_block("latest")["timestamp"]
    if now < info["unbondingAvailableAt"]:
        remaining = info["unbondingAvailableAt"] - now
        click.echo(f"Unbonding not ready. {remaining} seconds remaining.")
        return

    click.echo(f"Completing unstake of {info['unbonding'] / 10 ** 18} BLIND …")
    tx = complete_unstake(w3, wallet)
    if tx:
        click.echo(f"  Unstake completed: {tx}")
    else:
        click.echo("Unstake completion failed.", err=True)
        raise SystemExit(1)


@staking_group.command("status")
def staking_status() -> None:
    """Show BLIND stake status."""
    from blindference_node.registry import get_stake_info

    config = load_config()
    rpc = os.environ.get("BLF_RPC_URL") or os.environ.get("BLF_FHENIX_RPC")
    if not rpc:
        click.echo("Error: BLF_RPC_URL not set.", err=True)
        raise SystemExit(1)

    w3 = Web3(Web3.HTTPProvider(rpc))
    info = get_stake_info(w3, config.node_address)

    click.echo("=" * 60)
    click.echo("  BLIND Stake Status")
    click.echo("=" * 60)
    if info:
        click.echo(f"  Staked          : {info['staked'] / 10 ** 18:.2f} BLIND")
        click.echo(f"  Unbonding       : {info['unbonding'] / 10 ** 18:.2f} BLIND")
        if info["unbondingAvailableAt"] > 0:
            now = w3.eth.get_block("latest")["timestamp"]
            remaining = max(0, info["unbondingAvailableAt"] - now)
            click.echo(f"  Unbond ready in : {remaining}s")
        click.echo(f"  Failures        : {info['consecutiveFailures']}")
        click.echo(f"  Active          : {'Yes' if info['active'] else 'No'}")
    else:
        click.echo("  No stake info found (staking contract may not be deployed).")
    click.echo("=" * 60)
