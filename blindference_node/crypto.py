"""Cryptographic operations — AES-256-GCM and CoFHE bridge."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# CoFHE abstraction (mock for Phase 4, real SDK later)
# ---------------------------------------------------------------------------


class CoFHEClient(ABC):
    """Abstract interface for Fhenix CoFHE interactions."""

    @abstractmethod
    def decrypt(self, ciphertext_handle: str, permit: str) -> bytes:
        """Decrypt a CoFHE ciphertext handle using a sharing permit."""

    @abstractmethod
    def encrypt_for(self, plaintext: bytes, acl_address: str) -> str:
        """CoFHE-encrypt *plaintext* gated to *acl_address*."""


class MockCoFHEClient(CoFHEClient):
    """Mock CoFHE client — returns fixed keys for testing.

    In production this is replaced with the real ``@cofhe/sdk`` binding.
    """

    def __init__(self, fixed_key: bytes | None = None) -> None:
        self._key = fixed_key or os.urandom(32)
        self._handles: list[str] = []

    def decrypt(self, ciphertext_handle: str, permit: str) -> bytes:
        return self._key

    def encrypt_for(self, plaintext: bytes, acl_address: str) -> str:
        handle = "0x" + os.urandom(32).hex()
        self._handles.append(handle)
        return handle


# ---------------------------------------------------------------------------
# AES-256-GCM helpers
# ---------------------------------------------------------------------------


def generate_output_key() -> bytes:
    """Generate a fresh 256-bit AES key (32 bytes)."""
    return os.urandom(32)


def encrypt_output_blob(text: str, key: bytes) -> bytes:
    """Encrypt *text* with AES-256-GCM.

    Returns:
        ``iv (16) || ciphertext || tag (16)``
    """
    aes = AESGCM(key)
    iv = os.urandom(12)
    ct = aes.encrypt(iv, text.encode("utf-8"), None)
    return iv + ct


def decrypt_prompt_blob(blob: bytes, key: bytes) -> str:
    """Decrypt an AES-256-GCM blob produced by the client SDK.

    Blob format: ``iv (12) || ciphertext || tag (16)``.
    """
    iv = blob[:12]
    ct = blob[12:]
    aes = AESGCM(key)
    plaintext = aes.decrypt(iv, ct, None)
    return plaintext.decode("utf-8")


# ---------------------------------------------------------------------------
# Key splitting & CoFHE key storage helpers
# ---------------------------------------------------------------------------


def retrieve_prompt_key(
    cofhe: CoFHEClient, job_id: str, permit: str
) -> bytes:
    """Retrieve the AES prompt key from ``PromptKeyStore`` via CoFHE.

    In mock mode returns the CoFHE client's fixed key.  In production this
    calls ``PromptKeyStore.decryptForView()`` for both key halves and
    reconstructs ``Kp = KpH || KpL``.
    """
    # Production path (future):
    #   kp_high = cofhe.decrypt(f"PromptKeyStore.KpH.{job_id}", permit)
    #   kp_low  = cofhe.decrypt(f"PromptKeyStore.KpL.{job_id}", permit)
    #   return kp_high + kp_low
    return cofhe.decrypt(f"PromptKeyStore.{job_id}", permit)


def store_output_key_for_user(
    cofhe: CoFHEClient,
    job_id: str,
    ko: bytes,
    user_address: str,
) -> str:
    """Split *ko*, CoFHE-encrypt halves for *user_address*, store on-chain.

    Returns:
        A comma-separated string of the two CoFHE handles (``h_high,h_low``).
    """
    ko_high = ko[:16]
    ko_low = ko[16:]

    handle_high = cofhe.encrypt_for(ko_high, user_address)
    handle_low = cofhe.encrypt_for(ko_low, user_address)

    # Production path (future):
    #   call PromptKeyStore.storeOutputKey(job_id, handle_high, handle_low)
    return f"{handle_high},{handle_low}"
