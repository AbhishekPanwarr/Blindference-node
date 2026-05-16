"""Mock attestation backend — Phase 1 / developer nodes."""

import hashlib
import hmac

from blindference_node.attestation import AttestationBackend

_MOCK_KEY = b"weloveblindference"
_MOCK_RUNTIME_STRING = b"blindference-node-v0.1.0-mock"


class MockAttestationBackend(AttestationBackend):
    """Mock attestation — HMAC‑SHA256 with a hardcoded key.

    This backend provides zero trust guarantees.  It exists for developer
    testing and pipeline validation during Phase 1.  Nodes using mock
    attestation are capped at tier 0 (verifier‑only, low‑value jobs).
    """

    def get_quote(self, challenge: bytes) -> bytes:
        return hmac.new(_MOCK_KEY, challenge, hashlib.sha256).digest()

    def get_runtime_hash(self) -> bytes:
        return hashlib.sha256(_MOCK_RUNTIME_STRING).digest()

    def backend_type(self) -> str:
        return "mock"
