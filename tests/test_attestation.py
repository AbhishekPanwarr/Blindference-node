"""Tests for blindference_node.attestation."""

import hashlib
import hmac

from blindference_node.attestation.mock import MockAttestationBackend


def test_backend_type_is_mock():
    backend = MockAttestationBackend()
    assert backend.backend_type() == "mock"


def test_runtime_hash_is_constant():
    backend = MockAttestationBackend()
    h1 = backend.get_runtime_hash()
    h2 = backend.get_runtime_hash()
    assert h1 == h2
    assert len(h1) == 32
    assert h1 == hashlib.sha256(b"blindference-node-v0.1.0-mock").digest()


def test_quote_is_deterministic_hmac():
    backend = MockAttestationBackend()
    challenge = b"test-challenge-nonce"
    quote1 = backend.get_quote(challenge)
    quote2 = backend.get_quote(challenge)
    assert quote1 == quote2
    assert len(quote1) == 32

    expected = hmac.new(b"weloveblindference", challenge, hashlib.sha256).digest()
    assert quote1 == expected


def test_different_challenges_produce_different_quotes():
    backend = MockAttestationBackend()
    q1 = backend.get_quote(b"challenge-1")
    q2 = backend.get_quote(b"challenge-2")
    assert q1 != q2
