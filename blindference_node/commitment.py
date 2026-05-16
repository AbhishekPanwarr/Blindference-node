"""Blindference commitment construction per the whitepaper (Appendix B)."""

import hashlib


def compute_commitment(output_cid: str, output_text: str) -> bytes:
    """Build the binding commitment hash for an inference output.

    Construction:

        ``C = SHA‑256( SHA‑256(output_cid) ‖ SHA‑256(output_text) )``

    Args:
        output_cid: The IPFS CID of the encrypted output blob.
        output_text: The plaintext inference output.

    Returns:
        32‑byte commitment hash.
    """
    h_inner = hashlib.sha256(output_text.encode("utf-8")).digest()
    h_cid = hashlib.sha256(output_cid.encode("utf-8")).digest()
    return hashlib.sha256(h_cid + h_inner).digest()
