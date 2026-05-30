"""Blindference commitment construction per the whitepaper (Appendix B)."""

import hashlib
import re


def _normalize_output(text: str) -> str:
    """Normalize inference output before hashing.

    Collapses all whitespace (spaces, tabs, newlines) to single spaces and
    strips leading / trailing whitespace so trivial formatting differences
    across LLM invocations do not break quorum consensus.
    """
    return re.sub(r"\s+", " ", text.strip())


def compute_commitment(output_cid: str, output_text: str) -> bytes:
    """Build the binding commitment hash for an inference output.

    Construction:

        ``C = SHA‑256( SHA‑256(output_cid) ‖ SHA‑256(normalize(output_text)) )``

    Args:
        output_cid: The IPFS CID of the encrypted output blob.
        output_text: The plaintext inference output.

    Returns:
        32‑byte commitment hash.
    """
    normalized = _normalize_output(output_text)
    h_inner = hashlib.sha256(normalized.encode("utf-8")).digest()
    h_cid = hashlib.sha256(output_cid.encode("utf-8")).digest()
    return hashlib.sha256(h_cid + h_inner).digest()
