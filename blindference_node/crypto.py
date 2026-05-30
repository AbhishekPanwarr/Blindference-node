"""Cryptographic operations — AES-256-GCM and CoFHE bridge."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import subprocess
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

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

    def decrypt_prompt_key(self, high_handle: int, low_handle: int) -> tuple[int, int, str]:
        """Decrypt a 256‑bit AES key split into two ``uint128`` CoFHE handles.

        Returns:
            ``(high_plaintext, low_plaintext, permit_hash)``
        """
        high = self.decrypt(high_handle)
        low = self.decrypt(low_handle)
        return high, low, ""

    def encrypt_uint128_values(self, values: list[int]) -> list[dict[str, Any]]:
        """CoFHE‑encrypt a list of ``uint128`` values.

        Returns:
            A list of encrypted input dicts, each with ``ctHash``,
            ``securityZone``, ``utype``, and ``signature`` keys.
        """
        results: list[dict[str, Any]] = []
        for value in values:
            handle = self.encrypt(value)
            results.append({
                "ctHash": str(handle),
                "securityZone": 0,
                "utype": 6,  # Uint128
                "signature": "0x",
            })
        return results

    def store_prompt_key(
        self,
        task_id: str,
        prompt_key_store_address: str,
        encrypted_high_input: dict[str, Any],
        encrypted_low_input: dict[str, Any],
        allowed_nodes: list[str],
    ) -> str:
        """Store an encrypted key on-chain via PromptKeyStore.storeKey.

        Default implementation returns empty string (no-op for backends
        that don't support on-chain storage).
        """
        return ""


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
    """CoFHE client that keeps a persistent Node.js bridge process alive.

    Eliminates the ~10-30 second cold-start cost (module loading + CoFHE
    client handshake) on every operation by spawning the bridge once and
    reusing it across all calls via line-delimited JSON over stdin/stdout.
    """

    def __init__(self, wallet_private_key: str, rpc_url: str) -> None:
        self._pk = wallet_private_key
        self._rpc_url = rpc_url
        self._scripts_dir = os.path.join(os.path.dirname(__file__), "scripts")
        self._process: subprocess.Popen | None = None
        self._req_counter = 0
        self._closed = False

    def _validate_rpc(self) -> None:
        if "YOUR_KEY" in self._rpc_url or "demo" in self._rpc_url:
            raise CoFHEAPIError(
                f"Invalid CoFHE RPC URL: {self._rpc_url}\n"
                "The default Alchemy key is a placeholder. Set a real key:\n"
                "  export BLF_COFHE_ENDPOINT='https://arb-sepolia.g.alchemy.com/v2/YOUR_REAL_KEY'\n"
                "Or copy the ICL's RPC from its .env file."
            )

    def _ensure_process(self) -> subprocess.Popen:
        """Return the running bridge process, spawning it if necessary."""
        if self._process is not None and self._process.poll() is None:
            return self._process
        if self._closed:
            raise CoFHEAPIError("CoFHE bridge client has been closed")

        bridge_path = os.path.join(self._scripts_dir, "cofhe_bridge.mjs")
        if not os.path.exists(bridge_path):
            raise CoFHEAPIError(f"Bridge script not found: {bridge_path}")

        env = {
            **os.environ,
            "BLF_PRIVATE_KEY": self._pk,
            "NODE_NO_WARNINGS": "1",
        }
        self._process = subprocess.Popen(
            ["node", bridge_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        logger.info("CoFHE bridge process started (pid=%s)", self._process.pid)
        return self._process

    def _read_response_line(self, process: subprocess.Popen) -> str:
        """Read a single newline-terminated JSON line from stdout."""
        stdout = process.stdout
        if stdout is None:
            raise CoFHEAPIError("CoFHE bridge stdout pipe is missing")

        buffer = []
        while True:
            char = stdout.read(1)
            if not char:
                if self._process is not None and self._process.poll() is not None:
                    raise CoFHEAPIError(
                        f"CoFHE bridge process exited with code {self._process.returncode}"
                    )
                raise CoFHEAPIError("CoFHE bridge stdout closed unexpectedly")
            if char == "\n":
                break
            buffer.append(char)

        return "".join(buffer)

    def _run_bridge_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send *payload* to the persistent bridge and read the JSON response."""
        self._validate_rpc()
        process = self._ensure_process()

        self._req_counter += 1
        request_id = self._req_counter
        payload = {**payload, "_requestId": request_id}

        stdin = process.stdin
        if stdin is None:
            raise CoFHEAPIError("CoFHE bridge stdin pipe is missing")

        line = json.dumps(payload) + "\n"
        stdin.write(line)
        stdin.flush()

        raw = self._read_response_line(process)
        if not raw.strip():
            raise CoFHEAPIError("CoFHE bridge produced no output")

        try:
            response = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CoFHEAPIError(f"CoFHE bridge returned invalid JSON: {raw[:200]}...") from exc

        if not response.get("ok"):
            raise CoFHEAPIError(response.get("error") or "CoFHE bridge failed")

        return response

    def close(self) -> None:
        """Terminate the persistent bridge process."""
        self._closed = True
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except Exception:
                pass
            try:
                self._process.kill()
            except Exception:
                pass
            self._process = None

    def decrypt(self, ct_handle: int) -> int:
        # Fallback: use decrypt_prompt_key with a single handle (high) and ignore low
        high, _low, _permit_hash = self.decrypt_prompt_key(ct_handle, 0)
        return high

    def encrypt(self, value: int) -> int:
        results = self.encrypt_uint128_values([value])
        if not results:
            raise CoFHEAPIError("CoFHE encrypt returned no results")
        return int(results[0]["ctHash"])

    def decrypt_prompt_key(self, high_handle: int, low_handle: int) -> tuple[int, int, str]:
        payload = {
            "action": "decrypt_prompt_key",
            "privateKey": self._pk,
            "rpcUrl": self._rpc_url,
            "highHandle": hex(high_handle),
            "lowHandle": hex(low_handle),
        }
        result = self._run_bridge_json(payload)
        return int(result["high"]), int(result["low"]), str(result.get("permitHash", ""))

    def encrypt_uint128_values(self, values: list[int]) -> list[dict[str, Any]]:
        payload = {
            "action": "encrypt_uint128",
            "privateKey": self._pk,
            "rpcUrl": self._rpc_url,
            "values": [str(v) for v in values],
        }
        result = self._run_bridge_json(payload)
        return result.get("results", [])

    def store_prompt_key(
        self,
        task_id: str,
        prompt_key_store_address: str,
        encrypted_high_input: dict[str, Any],
        encrypted_low_input: dict[str, Any],
        allowed_nodes: list[str],
    ) -> str:
        """Store an encrypted key on-chain via PromptKeyStore.storeKey.

        The node wallet (which created the ciphertexts) calls this so
        the contract can verify the signer and grant ACL access.
        """
        payload = {
            "action": "store_prompt_key",
            "privateKey": self._pk,
            "rpcUrl": self._rpc_url,
            "taskId": task_id,
            "promptKeyStoreAddress": prompt_key_store_address,
            "encryptedHighInput": encrypted_high_input,
            "encryptedLowInput": encrypted_low_input,
            "allowedNodes": allowed_nodes,
        }
        result = self._run_bridge_json(payload)
        return str(result.get("txHash", ""))


# ---------------------------------------------------------------------------
# AES-256-GCM helpers
# ---------------------------------------------------------------------------


def generate_output_key() -> bytes:
    """Generate a fresh 256-bit AES key (32 bytes)."""
    return os.urandom(32)


def encrypt_output_blob(text: str, key: bytes) -> bytes:
    """Encrypt *text* with AES-256-GCM.

    Returns packed blob matching the Blindference frontend format:
        ``iv (12) || authTag (16) || ciphertext``
    """
    aes = AESGCM(key)
    iv = os.urandom(12)
    ct_with_tag = aes.encrypt(iv, text.encode("utf-8"), None)
    # AESGCM returns ciphertext || tag(16)
    ciphertext = ct_with_tag[:-16]
    auth_tag = ct_with_tag[-16:]
    return iv + auth_tag + ciphertext


def decrypt_prompt_blob(blob: bytes, key: bytes) -> str:
    """Decrypt an AES-256-GCM blob.

    Blob format (Blindference frontend):
        ``iv (12) || authTag (16) || ciphertext``
    """
    if len(blob) < 28:
        raise ValueError(f"Blob too short ({len(blob)} bytes) — need at least 28 for iv+tag")
    iv = blob[:12]
    auth_tag = blob[12:28]
    ciphertext = blob[28:]
    aes = AESGCM(key)
    # AESGCM expects ciphertext || tag
    plaintext = aes.decrypt(iv, ciphertext + auth_tag, None)
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
