"""Tests for blindference_node.commitment."""

import hashlib

from blindference_node.commitment import compute_commitment


def test_commitment_deterministic():
    """Same inputs produce the same commitment."""
    c1 = compute_commitment("QmTest123", "The output text")
    c2 = compute_commitment("QmTest123", "The output text")
    assert c1 == c2
    assert len(c1) == 32


def test_different_cid_different_commitment():
    """Different CID → different commitment."""
    c1 = compute_commitment("QmA", "same text")
    c2 = compute_commitment("QmB", "same text")
    assert c1 != c2


def test_different_text_different_commitment():
    """Different output text → different commitment."""
    c1 = compute_commitment("QmC", "text A")
    c2 = compute_commitment("QmC", "text B")
    assert c1 != c2


def test_known_vector():
    """Test against a hand-computed known vector."""
    cid = "QmTestVector"
    text = "Hello, Blindference!"

    h_inner = hashlib.sha256(text.encode("utf-8")).digest()
    h_cid = hashlib.sha256(cid.encode("utf-8")).digest()
    expected = hashlib.sha256(h_cid + h_inner).digest()

    assert compute_commitment(cid, text) == expected


def test_known_vector_2():
    """Another known vector."""
    cid = "QmAnotherTest"
    text = "The quick brown fox jumps over the lazy dog"

    h_inner = hashlib.sha256(text.encode("utf-8")).digest()
    h_cid = hashlib.sha256(cid.encode("utf-8")).digest()
    expected = hashlib.sha256(h_cid + h_inner).digest()

    assert compute_commitment(cid, text) == expected
