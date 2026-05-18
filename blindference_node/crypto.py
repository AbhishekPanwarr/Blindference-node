"""Cryptographic operations — AES-256-GCM and CoFHE bridge."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import aiohttp
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from eth_account import Account
from eth_account.messages import encode_typed_data

if TYPE_CHECKING:
    from blindference_node.config import Config

logger = logging.getLogger("blindference-node")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CoFHEAPIError(Exception):
    """Raised when a CoFHE API call fails."""


# ---------------------------------------------------------------------------
# CoFHE abstraction
# ---------------------------------------------------------------------------


class CoFHEClient(ABC):
    """Abstract interface for Fhenix CoFHE interactions.

    Handles are on‑chain ``uint256`` identifiers.  Plaintext values are
    128‑bit unsigned integers (``uint128``).
    """

    @abstractmethod
    def decrypt(self, ct_handle: int) -> int:
        """Decrypt *ct_handle* and return the ``uint128`` plaintext."""

    @abstractmethod
    def encrypt(self, value: int) -> int:
        """CoFHE‑encrypt *value* and return the ``uint256`` handle."""


# ---------------------------------------------------------------------------
# CoFHE factory
# ---------------------------------------------------------------------------


def get_cofhe_client(config: Config, wallet_private_key: str) -> CoFHEClient:
    """Return the CoFHE client selected by ``config.cofhe_mode``.

    ``"python"`` → ``CoFHERealClient`` (HTTP to Fhenix API).
    ``"bridge"`` → ``CoFHEBridgeClient`` (Node.js subprocess using @cofhe/sdk/node).
    """
    mode = config.cofhe_mode.lower()
    if mode == "python":
        return CoFHERealClient(
            wallet_private_key=wallet_private_key,
            endpoint=config.cofhe_endpoint,
            chain_id=config.cofhe_chain_id,
        )
    if mode == "bridge":
        return CoFHEBridgeClient(wallet_private_key=wallet_private_key, rpc_url=config.cofhe_endpoint)
    logger.warning("Unknown cofhe_mode=%r — falling back to bridge", config.cofhe_mode)
    return CoFHEBridgeClient(wallet_private_key=wallet_private_key, rpc_url=config.cofhe_endpoint)


# ---------------------------------------------------------------------------
# CoFHERealClient (Python HTTP)
# ---------------------------------------------------------------------------


@dataclass
class _SealingPermit:
    issuer: str
    expiration: int
    sealing_public_hex: str
    signature: str
    sealing_private_key: object  # X25519PrivateKey — never serialised


class CoFHERealClient(CoFHEClient):
    """Real CoFHE client — talks to the Fhenix CoFHE HTTP API.

    Creates an EIP‑712 self‑permit with an X25519 sealing keypair,
    sends it to the CoFHE endpoint for decryption, and unseals the
    returned value via ECIES (X25519 + HKDF + AES‑GCM).

    Args:
        wallet_private_key: Hex private key of the node wallet.
        endpoint: Base URL of the CoFHE API.
        chain_id: EVM chain ID (e.g. 421614 for Arbitrum Sepolia).
    """

    def __init__(
        self,
        wallet_private_key: str,
        endpoint: str,
        chain_id: int = 421614,
    ) -> None:
        raw = wallet_private_key
        if raw.startswith("0x") or raw.startswith("0X"):
            raw = raw[2:]
        self._wallet = Account.from_key(raw)
        self._endpoint = endpoint.rstrip("/")
        self._chain_id = chain_id
        self._permit: _SealingPermit | None = None

    # ---- permit -----------------------------------------------------------

    def _ensure_permit(self) -> _SealingPermit:
        now = int(time.time())
        if self._permit is not None and self._permit.expiration > now + 3600:
            return self._permit

        sk = X25519PrivateKey.generate()
        pk_bytes = sk.public_key().public_bytes_raw()
        expiration = now + 7 * 24 * 3600

        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Permit": [
                    {"name": "issuer", "type": "address"},
                    {"name": "expiration", "type": "uint256"},
                    {"name": "sealingKey", "type": "bytes32"},
                ],
            },
            "primaryType": "Permit",
            "domain": {
                "name": "CoFHE",
                "version": "1",
                "chainId": self._chain_id,
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            },
            "message": {
                "issuer": self._wallet.address,
                "expiration": expiration,
                "sealingKey": "0x" + pk_bytes.hex(),
            },
        }
        structured = encode_typed_data(full_message=typed_data)
        signed = self._wallet.sign_message(structured)

        self._permit = _SealingPermit(
            issuer=self._wallet.address,
            expiration=expiration,
            sealing_public_hex="0x" + pk_bytes.hex(),
            signature="0x" + signed.signature.hex(),
            sealing_private_key=sk,
        )
        logger.debug("Permit renewed (expires in %ds)", expiration - now)
        return self._permit

    # ---- API calls --------------------------------------------------------

    def decrypt(self, ct_handle: int) -> int:
        permit = self._ensure_permit()
        payload = {
            "jsonrpc": "2.0",
            "method": "cofhe_decryptForView",
            "params": [
                hex(ct_handle),
                {
                    "issuer": permit.issuer,
                    "expiration": permit.expiration,
                    "sealingKey": permit.sealing_public_hex,
                    "signature": permit.signature,
                },
            ],
            "id": 1,
        }
        return _sync_call(self._endpoint, payload, permit.sealing_private_key)

    def encrypt(self, value: int) -> int:
        payload = {
            "jsonrpc": "2.0",
            "method": "cofhe_encrypt",
            "params": [
                hex(value),
                "uint128",
                self._wallet.address,
            ],
            "id": 1,
        }
        return _sync_encrypt(self._endpoint, payload)


def _sync_call(endpoint: str, payload: dict, sealing_private_key: object) -> int:
    """Synchronous HTTP call to the CoFHE API (called via ``asyncio.to_thread``)."""
    import requests as _requests

    try:
        resp = _requests.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except _requests.RequestException as exc:
        raise CoFHEAPIError(f"CoFHE decrypt request failed: {exc}") from exc

    if "error" in result:
        raise CoFHEAPIError(f"CoFHE decrypt error: {result['error']}")

    sealed_hex = result.get("result", {}).get("sealedValue", "")
    if not sealed_hex:
        raise CoFHEAPIError("CoFHE response missing sealedValue")

    sealed_bytes = bytes.fromhex(sealed_hex.replace("0x", ""))
    return _unseal(sealed_bytes, sealing_private_key)


def _sync_encrypt(endpoint: str, payload: dict) -> int:
    import requests as _requests

    try:
        resp = _requests.post(
            endpoint, json=payload,
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        resp.raise_for_status()
        result = resp.json()
    except _requests.RequestException as exc:
        raise CoFHEAPIError(f"CoFHE encrypt request failed: {exc}") from exc

    if "error" in result:
        raise CoFHEAPIError(f"CoFHE encrypt error: {result['error']}")

    handle_hex = result.get("result", {}).get("handle", "")
    if not handle_hex:
        raise CoFHEAPIError("CoFHE response missing handle")

    return int(handle_hex, 16)


def _unseal(sealed_bytes: bytes, sealing_private_key: object) -> int:
    """ECIES unseal: X25519 → HKDF → AES‑GCM decrypt."""
    if len(sealed_bytes) < 65:
        raise CoFHEAPIError(f"Sealed value too short: {len(sealed_bytes)} bytes")

    eph_pub = X25519PublicKey.from_public_bytes(sealed_bytes[:32])
    iv = sealed_bytes[32:44]
    ciphertext = sealed_bytes[44:]

    shared = sealing_private_key.exchange(eph_pub)
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=b"CoFHE seal")
    aes_key = hkdf.derive(shared)

    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(iv, ciphertext, None)
    return int.from_bytes(plaintext, "big")


# ---------------------------------------------------------------------------
# CoFHEBridgeClient (TypeScript fallback)
# ---------------------------------------------------------------------------


class CoFHEBridgeClient(CoFHEClient):
    """CoFHE client that spawns a Node.js TypeScript bridge.

    Uses ``@cofhe/sdk/node`` + viem to call the Fhenix CoFHE coprocessor
    through the Arbitrum Sepolia RPC.  The *rpc_url* must point to an
    Arbitrum Sepolia RPC endpoint (e.g. Alchemy / Infura).
    """

    def __init__(self, wallet_private_key: str, rpc_url: str) -> None:
        self._pk = wallet_private_key
        self._rpc_url = rpc_url
        self._scripts_dir = os.path.join(os.path.dirname(__file__), "..", "scripts")

    def _run_bridge(self, script: str, *args: str) -> int:
        cmd = ["npx", "ts-node", os.path.join(self._scripts_dir, script), *args, self._rpc_url]
        env = {**os.environ, "BLF_PRIVATE_KEY": self._pk}
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode != 0:
            raise CoFHEAPIError(f"Bridge {script} failed: {result.stderr.strip()}")
        return int(result.stdout.strip(), 0)

    def decrypt(self, ct_handle: int) -> int:
        return self._run_bridge("cofhe_decrypt.ts", hex(ct_handle))

    def encrypt(self, value: int) -> int:
        return self._run_bridge("cofhe_encrypt.ts", hex(value))


# ---------------------------------------------------------------------------
# AES-256-GCM helpers
# ---------------------------------------------------------------------------


def generate_output_key() -> bytes:
    """Generate a fresh 256-bit AES key (32 bytes)."""
    return os.urandom(32)


def encrypt_output_blob(text: str, key: bytes) -> bytes:
    """Encrypt *text* with AES-256-GCM.

    Returns:
        ``iv (12) || ciphertext + tag (16)``
    """
    aes = AESGCM(key)
    iv = os.urandom(12)
    ct = aes.encrypt(iv, text.encode("utf-8"), None)
    return iv + ct


def decrypt_prompt_blob(blob: bytes, key: bytes) -> str:
    """Decrypt an AES-256-GCM blob.

    Blob format: ``iv (12) || ciphertext || tag (16)``.
    """
    iv = blob[:12]
    ct = blob[12:]
    aes = AESGCM(key)
    plaintext = aes.decrypt(iv, ct, None)
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Key reconstruction helpers
# ---------------------------------------------------------------------------


def reconstruct_key(high_uint128: int, low_uint128: int) -> bytes:
    """Reconstruct a 32‑byte AES key from two ``uint128`` halves."""
    return high_uint128.to_bytes(16, "big") + low_uint128.to_bytes(16, "big")


def split_key_for_cofhe(key: bytes) -> tuple[int, int]:
    """Split a 32‑byte AES key into two ``uint128`` integers."""
    return (
        int.from_bytes(key[:16], "big"),
        int.from_bytes(key[16:], "big"),
    )


def format_output_key_handle(high_handle: int, low_handle: int) -> str:
    """Format two CoFHE handles as a single hex string for ICL submission."""
    return "0x" + high_handle.to_bytes(32, "big").hex() + low_handle.to_bytes(32, "big").hex()
