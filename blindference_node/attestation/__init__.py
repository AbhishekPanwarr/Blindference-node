"""Attestation backend interface for Blindference nodes."""

from abc import ABC, abstractmethod


class AttestationBackend(ABC):
    """Pluggable attestation backend.

    Each backend type (mock, tpm, sev, tdx) implements this interface.
    The ICL verifies the attestation quote against the appropriate root of
    trust and returns a time‑bound certificate.
    """

    @abstractmethod
    def get_quote(self, challenge: bytes) -> bytes:
        """Generate an attestation quote binding *challenge* to this runtime.

        Args:
            challenge: A random nonce from the ICL (prevents replay).

        Returns:
            Raw quote bytes to be hex‑encoded and sent to the ICL.
        """

    @abstractmethod
    def get_runtime_hash(self) -> bytes:
        """Return a SHA‑256 hash of the inference engine runtime.

        This proves the node is running the expected software stack.
        """

    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend identifier.

        One of: ``"mock"``, ``"tpm"``, ``"sev"``, ``"tdx"``.
        """
