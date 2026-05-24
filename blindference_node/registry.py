"""On‑chain contract wrappers for Blindference node registration."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

from eth_account.messages import encode_defunct
from eth_account.signers.local import LocalAccount

from blindference_node.config import Config

# ---------------------------------------------------------------------------
# Paths & addresses
# ---------------------------------------------------------------------------

_ABI_DIR = os.path.join(os.path.dirname(__file__), "contracts", "abis")

# Arbitrum Sepolia (chain 421614) — proxy addresses
_CONTRACTS = {
    "fhenix_testnet": {
        "NodeAttestationRegistry": "0xB54e019e9717a8Ed4746bA9d7F1A3F83cf0a35E0",
        "NodeOperatorRegistry": "0x0000000000000000000000000000000000000000",
        "NodeRegistry": "0x72C0Ead949Fd2C346598a30AF1A69c3c5Cb86082",  # Deployed proxy
        "PromptKeyStore": "0x1E22dD12f448B15f1Ca8560fB6B4463834FaAf73",
        "ExecutionCommitmentRegistry": "0xcd45aefE9a16772528fa30B7d47958a95e83440C",
        "BlindferenceStaking": "0x222Ac74201Ed58915e42Ee5be626d939fd234D0b",
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_abi(name: str) -> list[dict[str, Any]]:
    path = os.path.join(_ABI_DIR, f"{name}.json")
    if not os.path.exists(path):
        raise FileNotFoundError(f"ABI file not found: {path}")
    with open(path) as f:
        data = json.load(f)
    return data["abi"]


def _get_contract(w3, name: str, address: str):
    return w3.eth.contract(address=address, abi=_load_abi(name))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_node_registry(w3):
    """Return a ``NodeAttestationRegistry`` contract handle for *w3*."""
    network_contracts = _CONTRACTS.get("fhenix_testnet", {})
    addr = network_contracts.get("NodeAttestationRegistry", "")
    if not addr or addr == "0x" + "0" * 40:
        raise ValueError("NodeAttestationRegistry address not configured")
    return _get_contract(w3, "NodeAttestationRegistry", addr)


def get_new_node_registry(w3):
    """Return new ``NodeRegistry`` contract handle, or ``None`` if not deployed."""
    network_contracts = _CONTRACTS.get("fhenix_testnet", {})
    addr = network_contracts.get("NodeRegistry", "")
    if not addr or addr == "0x" + "0" * 40 or int(addr, 16) == 0:
        return None
    try:
        return _get_contract(w3, "NodeRegistry", addr)
    except FileNotFoundError:
        return None


def is_node_registered(w3, node_address: str) -> tuple[bool, bool]:
    """Check whether a node is already registered and active on-chain.

    Returns:
        ``(registered, active)`` where *registered* means the node has a
        non-zero operator record and *active* means ``isActive()`` returns
        ``True`` (attestation + heartbeat are both valid).
    """
    contract = get_new_node_registry(w3)
    if contract is None:
        return False, False
    try:
        active = contract.functions.isActive(node_address).call()
        node_data = contract.functions.getNode(node_address).call()
        registered = node_data[0] != "0x" + "0" * 40  # operator != zero address
        return registered, active
    except Exception:
        return False, False


def get_node_operator_registry(w3):
    """Return ``NodeOperatorRegistry`` contract handle, or ``None`` if not deployed."""
    network_contracts = _CONTRACTS.get("fhenix_testnet", {})
    addr = network_contracts.get("NodeOperatorRegistry", "")
    if not addr or addr == "0x" + "0" * 40 or int(addr, 16) == 0:
        return None
    return _get_contract(w3, "NodeOperatorRegistry", addr)


def register_node(
    w3,
    config: Config,
    wallet: LocalAccount,
    stake_wei: int = 0,
    cert_hash: str = "",
    attestation_expiry: int = 0,
) -> str | None:
    """Register this node on‑chain with best‑effort contract resolution.

    Attempts (in order):
        1. ``NodeRegistry.register(…)`` (new, preferred).
        2. ``NodeOperatorRegistry.register(…)`` (legacy).
        3. ``NodeAttestationRegistry.commit(…)`` as a fallback attestation record.
        4. Logs a warning if neither path is viable.

    Args:
        w3: A connected ``Web3`` instance.
        config: The node ``Config``.
        wallet: The unlocked node wallet (for signing).
        stake_wei: Native token amount to stake (in wei).
        cert_hash: The attestation certificate hash from the ICL.
        attestation_expiry: Unix timestamp when attestation expires.

    Returns:
        Transaction hash (hex) on success, or ``None`` if registration was
        skipped (e.g. no contract available).
    """
    # ── path 1: new NodeRegistry ──────────────────────────────────────
    new_registry = get_new_node_registry(w3)
    if new_registry is not None:
        return _register_via_node_registry(
            w3, new_registry, config, wallet, stake_wei, cert_hash, attestation_expiry
        )

    # ── path 2: NodeOperatorRegistry (legacy) ───────────────────────
    operator_registry = get_node_operator_registry(w3)
    if operator_registry is not None:
        return _register_via_operator_registry(
            w3, operator_registry, config, wallet, stake_wei, cert_hash
        )

    # ── path 3: NodeAttestationRegistry.commit ──────────────────────
    attestation_registry = None
    try:
        attestation_registry = get_node_registry(w3)
    except (ValueError, FileNotFoundError):
        pass

    if attestation_registry is not None:
        return _register_via_attestation_commit(
            w3, attestation_registry, config, wallet, cert_hash
        )

    # ── path 4: no viable contract ──────────────────────────────────
    print(
        "Warning: No on‑chain registration contract is available. "
        "The node will not be registered on‑chain, but the ICL may still "
        "include it in job assignments after successful attestation.",
        file=sys.stderr,
    )
    return None


# ---------------------------------------------------------------------------
# Path 1 — NodeRegistry.register() (new, preferred)
# ---------------------------------------------------------------------------


def _register_via_node_registry(
    w3,
    contract,
    config: Config,
    wallet: LocalAccount,
    stake_wei: int,
    cert_hash: str,
    attestation_expiry: int,
) -> str:
    print(f"  Registering via NodeRegistry … stake={stake_wei} wei")

    tx = contract.functions.register(
        config.tier,
        _to_bytes32(cert_hash),
        attestation_expiry,
        config.supported_model_ids,
    ).build_transaction(
        {
            "from": wallet.address,
            "value": stake_wei,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 500_000,
            "gasPrice": _estimate_gas_price(w3),
        }
    )

    signed = wallet.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    _print_tx(receipt.transactionHash.hex(), "Registration tx")
    return receipt.transactionHash.hex()


# ---------------------------------------------------------------------------
# Path 2 — NodeOperatorRegistry.register() (legacy)
# ---------------------------------------------------------------------------


def _estimate_gas_price(w3) -> int:
    """Return current gas price with a 50% buffer to avoid base-fee rejections."""
    base = w3.eth.gas_price
    # Add 50% buffer; on Arbitrum Sepolia base fee can spike above gas_price
    return int(base * 1.5)


def _explorer_url(tx_hash: str) -> str | None:
    """Return a human-readable block-explorer URL for Arbitrum Sepolia."""
    if not tx_hash or not tx_hash.startswith("0x"):
        return None
    return f"https://sepolia.arbiscan.io/tx/{tx_hash}"


def _print_tx(tx_hash: str, label: str = "Transaction") -> None:
    """Pretty-print a transaction hash with explorer link."""
    print(f"  {label:<18} : {tx_hash}")
    url = _explorer_url(tx_hash)
    if url:
        print(f"  {'Explorer':<18} : {url}")


def _register_via_operator_registry(
    w3,
    contract,
    config: Config,
    wallet: LocalAccount,
    stake_wei: int,
    cert_hash: str,
) -> str:
    print(f"  Registering via NodeOperatorRegistry (legacy) … stake={stake_wei} wei")

    # Convert tier → model_tiers (uint8 list matching supported models)
    model_tiers: list[int] = [config.tier for _ in config.supported_model_ids]

    tx = contract.functions.register(
        cert_hash,  # ipfsCID — we store the cert hash as identifier
        model_tiers,
        "unknown",  # location
        config.zdr_compliant,
        "global",   # jurisdiction
    ).build_transaction(
        {
            "from": wallet.address,
            "value": stake_wei,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 500_000,
            "gasPrice": _estimate_gas_price(w3),
        }
    )

    signed = wallet.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    _print_tx(receipt.transactionHash.hex(), "Registration tx")
    return receipt.transactionHash.hex()


# ---------------------------------------------------------------------------
# Path 2 — NodeAttestationRegistry.commit()
# ---------------------------------------------------------------------------

# keccak256("blindference.node.availability.v1")
# Must match the attestation type that get_active_nodes() passes to
# NodeAttestationRegistry.hasValid().
_DEFAULT_ATTESTATION_TYPE = bytes.fromhex(
    "ca0ac5323d72ba0e8e9c7657401f1b7e45a00f51fe8b62e62c975d72ed2b17a4"
)


def _register_via_attestation_commit(
    w3,
    contract,
    config: Config,
    wallet: LocalAccount,
    cert_hash: str,
) -> str:
    print("Registering via NodeAttestationRegistry.commit() …")

    doc_hash = _to_bytes32(cert_hash)
    now = int(time.time())
    effective_at = now
    expires_at = now + 172_800  # 48 hours
    counterparty = "0x0000000000000000000000000000000000000000"

    # Compute the EIP‑712‑style digest that the contract expects us to sign
    digest = contract.functions.digest(
        wallet.address,
        _DEFAULT_ATTESTATION_TYPE,
        doc_hash,
        counterparty,
        effective_at,
        expires_at,
    ).call()

    # Sign the digest
    message = encode_defunct(hexstr=digest.hex())
    signed = wallet.sign_message(message)

    tx = contract.functions.commit(
        wallet.address,
        _DEFAULT_ATTESTATION_TYPE,
        doc_hash,
        counterparty,
        effective_at,
        expires_at,
        signed.signature,
    ).build_transaction(
        {
            "from": wallet.address,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 300_000,
            "gasPrice": _estimate_gas_price(w3),
        }
    )

    signed_tx = wallet.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    _print_tx(receipt.transactionHash.hex(), "Attestation tx")
    return receipt.transactionHash.hex()


# ---------------------------------------------------------------------------
# Phase 3 — Heartbeat & Attestation updates
# ---------------------------------------------------------------------------


def update_heartbeat(w3, config: Config, wallet: LocalAccount) -> None:
    """Send an on‑chain heartbeat to keep the node active.

    If ``NodeRegistry`` is deployed, calls ``heartbeat()``.
    Otherwise falls back to ``NodeOperatorRegistry.updateHeartbeat()``.
    If neither is available, logs a warning — the ICL will still track
    liveness via its own heartbeat endpoint (Phase 3+).

    Never raises; failures are logged and skipped.
    """
    # Try new NodeRegistry first
    new_registry = get_new_node_registry(w3)
    if new_registry is not None:
        try:
            tx = new_registry.functions.heartbeat().build_transaction(
                {
                    "from": wallet.address,
                    "nonce": w3.eth.get_transaction_count(wallet.address),
                    "gas": 100_000,
                    "gasPrice": _estimate_gas_price(w3),
                }
            )
            signed = wallet.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _print_tx(tx_hash.hex(), "Heartbeat tx")
        except Exception as exc:
            print(f"Heartbeat failed: {exc}", file=sys.stderr)
        return

    # Fallback to legacy NodeOperatorRegistry
    operator_registry = get_node_operator_registry(w3)
    if operator_registry is not None:
        try:
            tx = operator_registry.functions.updateHeartbeat().build_transaction(
                {
                    "from": wallet.address,
                    "nonce": w3.eth.get_transaction_count(wallet.address),
                    "gas": 100_000,
                    "gasPrice": _estimate_gas_price(w3),
                }
            )
            signed = wallet.sign_transaction(tx)
            tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
            _print_tx(tx_hash.hex(), "Heartbeat tx")
        except Exception as exc:
            print(f"Heartbeat failed: {exc}", file=sys.stderr)
        return

    print("Heartbeat skipped: No on‑chain registry deployed", file=sys.stderr)


def update_attestation(
    w3,
    config: Config,
    wallet: LocalAccount,
    cert_hash: str,
    expiry: int,
) -> None:
    """Record a renewed attestation certificate on‑chain.

    Currently a stub — logs the new certificate details.  A future
    implementation will call ``NodeAttestationRegistry.commit()`` or
    the equivalent on the operator registry.
    """
    print(
        f"Attestation update on‑chain: certHash={cert_hash}, expiry={expiry}",
        file=sys.stderr,
    )


# ---------------------------------------------------------------------------
# Phase 4 — Commitment posting (on‑chain, opt‑in)
# ---------------------------------------------------------------------------


def get_commitment_registry(w3):
    """Return an ``ExecutionCommitmentRegistry`` contract handle, or ``None``."""
    network_contracts = _CONTRACTS.get("fhenix_testnet", {})
    addr = network_contracts.get("ExecutionCommitmentRegistry", "")
    if not addr or addr == "0x" + "0" * 40 or int(addr, 16) == 0:
        return None
    try:
        return _get_contract(w3, "ExecutionCommitmentRegistry", addr)
    except FileNotFoundError:
        return None


def post_commitment_seal(
    w3,
    wallet: LocalAccount,
    invocation_id: int,
    role: int,
    digest: bytes,
) -> str | None:
    """Post a sealed commitment to ``ExecutionCommitmentRegistry.commit()``.

    Args:
        w3: Connected Web3 instance.
        wallet: The node wallet for signing.
        invocation_id: The on‑chain invocation identifier.
        role: 0 = leader, 1 = verifier.
        digest: 32‑byte commitment digest.

    Returns:
        Transaction hash, or ``None`` if the registry is not available.
    """
    contract = get_commitment_registry(w3)
    if contract is None:
        print("Commitment seal skipped: ExecutionCommitmentRegistry not deployed",
              file=sys.stderr)
        return None

    try:
        tx = contract.functions.commit(
            invocation_id, role, digest
        ).build_transaction({
            "from": wallet.address,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 200_000,
            "gasPrice": _estimate_gas_price(w3),
        })
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Commitment seal failed: {exc}", file=sys.stderr)
        return None


def post_commitment_reveal(
    w3,
    wallet: LocalAccount,
    invocation_id: int,
    role: int,
    output_handle: bytes,
    salt: bytes,
) -> str | None:
    """Reveal a previously sealed commitment.

    Args:
        w3: Connected Web3 instance.
        wallet: The node wallet for signing.
        invocation_id: The on‑chain invocation identifier.
        role: 0 = leader, 1 = verifier.
        output_handle: 32‑byte hash of the output CID.
        salt: 32‑byte salt (use SHA‑256 of output text).

    Returns:
        Transaction hash, or ``None`` if the registry is not available.
    """
    contract = get_commitment_registry(w3)
    if contract is None:
        return None

    try:
        tx = contract.functions.reveal(
            invocation_id, role, output_handle, salt
        ).build_transaction({
            "from": wallet.address,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 200_000,
            "gasPrice": _estimate_gas_price(w3),
        })
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Commitment reveal failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Phase 4 — Output key storage
# ---------------------------------------------------------------------------


def store_output_key(
    w3,
    config: Config,
    wallet: LocalAccount,
    job_id: str,
    high_handle: int,
    low_handle: int,
    user_address: str,
) -> dict | None:
    """Store the output AES key halves on‑chain via PromptKeyStore.

    Calls ``PromptKeyStore.storeOutputKey(bytes32 jobId, uint256 KoH, uint256 KoL, address user)``.
    When ``config.skip_output_key_storage`` is ``True``, logs the intent and returns a dummy result
    without sending an on‑chain transaction.
    """
    if config.skip_output_key_storage:
        print(
            f"Output key storage skipped (skip_output_key_storage=True): "
            f"job={job_id} user={user_address} handles={high_handle},{low_handle}",
            file=sys.stderr,
        )
        return {"status": "skipped", "tx_hash": None}

    network_contracts = _CONTRACTS.get(config.network, {})
    addr = network_contracts.get("PromptKeyStore", "")
    if not addr or int(addr, 16) == 0:
        print("Output key storage skipped: PromptKeyStore not configured", file=sys.stderr)
        return None

    try:
        contract = _get_contract(w3, "PromptKeyStore", addr)
        job_id_bytes = bytes.fromhex(job_id.replace("0x", ""))
        tx = contract.functions.storeOutputKey(
            job_id_bytes,
            high_handle,
            low_handle,
            w3.to_checksum_address(user_address),
        ).build_transaction({
            "from": wallet.address,
            "nonce": w3.eth.get_transaction_count(wallet.address),
            "gas": 300_000,
            "gasPrice": _estimate_gas_price(w3),
        })
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        _print_tx(receipt.transactionHash.hex(), "Output-key tx")
        return {"status": "stored", "tx_hash": receipt.transactionHash.hex()}
    except Exception as exc:
        print(f"Output key storage failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _to_bytes32(value: str) -> bytes:
    """Convert a hex string or arbitrary string to a 32‑byte value."""
    if value.startswith("0x") or value.startswith("0X"):
        raw = bytes.fromhex(value[2:])
    else:
        raw = value.encode("utf-8")
    if len(raw) > 32:
        import hashlib
        return hashlib.sha256(raw).digest()
    return raw.ljust(32, b"\x00")


# ---------------------------------------------------------------------------
# Phase 4 — BLIND Token Staking
# ---------------------------------------------------------------------------


def get_staking_contract(w3):
    """Return a ``BlindferenceStaking`` contract handle, or ``None``."""
    network_contracts = _CONTRACTS.get("fhenix_testnet", {})
    addr = network_contracts.get("BlindferenceStaking", "")
    if not addr or addr == "0x" + "0" * 40 or int(addr, 16) == 0:
        return None
    try:
        return _get_contract(w3, "BlindferenceStaking", addr)
    except FileNotFoundError:
        return None


def stake_blind(w3, wallet: LocalAccount, amount_wei: int) -> str | None:
    """Stake BLIND tokens. Requires prior ERC-20 approve."""
    contract = get_staking_contract(w3)
    if contract is None:
        print("Staking skipped: BlindferenceStaking not deployed", file=sys.stderr)
        return None

    try:
        tx = contract.functions.stake(amount_wei).build_transaction(
            {
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 200_000,
                "gasPrice": _estimate_gas_price(w3),
            }
        )
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        _print_tx(receipt.transactionHash.hex(), "Stake tx")
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Stake failed: {exc}", file=sys.stderr)
        return None


def approve_blind(w3, wallet: LocalAccount, amount_wei: int) -> str | None:
    """Approve BlindferenceStaking to spend BLIND tokens."""
    contract = get_staking_contract(w3)
    if contract is None:
        print("Approve skipped: BlindferenceStaking not deployed", file=sys.stderr)
        return None

    blind_token = _get_contract(w3, "BLIND", contract.functions.blindToken().call())
    try:
        tx = blind_token.functions.approve(contract.address, amount_wei).build_transaction(
            {
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 100_000,
                "gasPrice": _estimate_gas_price(w3),
            }
        )
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        _print_tx(receipt.transactionHash.hex(), "Approve tx")
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Approve failed: {exc}", file=sys.stderr)
        return None


def initiate_unstake(w3, wallet: LocalAccount) -> str | None:
    """Initiate BLIND unstake (starts 96h unbonding)."""
    contract = get_staking_contract(w3)
    if contract is None:
        print("Unstake skipped: BlindferenceStaking not deployed", file=sys.stderr)
        return None

    try:
        tx = contract.functions.initiateUnstake().build_transaction(
            {
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 150_000,
                "gasPrice": _estimate_gas_price(w3),
            }
        )
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        _print_tx(receipt.transactionHash.hex(), "Unstake-init tx")
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Unstake initiation failed: {exc}", file=sys.stderr)
        return None


def complete_unstake(w3, wallet: LocalAccount) -> str | None:
    """Complete BLIND unstake after unbonding period."""
    contract = get_staking_contract(w3)
    if contract is None:
        print("Unstake completion skipped: BlindferenceStaking not deployed", file=sys.stderr)
        return None

    try:
        tx = contract.functions.completeUnstake().build_transaction(
            {
                "from": wallet.address,
                "nonce": w3.eth.get_transaction_count(wallet.address),
                "gas": 150_000,
                "gasPrice": _estimate_gas_price(w3),
            }
        )
        signed = wallet.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
        _print_tx(receipt.transactionHash.hex(), "Unstake-complete tx")
        return receipt.transactionHash.hex()
    except Exception as exc:
        print(f"Unstake completion failed: {exc}", file=sys.stderr)
        return None


def get_stake_info(w3, node_address: str) -> dict | None:
    """Return stake info for a node."""
    contract = get_staking_contract(w3)
    if contract is None:
        return None
    try:
        info = contract.functions.getStakeInfo(node_address).call()
        return {
            "staked": info[0],
            "unbonding": info[1],
            "unbondingAvailableAt": info[2],
            "consecutiveFailures": info[3],
            "active": info[4],
        }
    except Exception:
        return None
