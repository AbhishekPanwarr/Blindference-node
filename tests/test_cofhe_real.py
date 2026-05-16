"""Tests for CoFHE real client — key reconstruction and mock API."""

import hashlib
import hmac

import pytest

from blindference_node.crypto import (
    CoFHEAPIError,
    CoFHEBridgeClient,
    CoFHERealClient,
    MockCoFHEClient,
    format_output_key_handle,
    get_cofhe_client,
    reconstruct_key,
    split_key_for_cofhe,
)


# ==================================================================
# Key reconstruction
# ==================================================================


def test_reconstruct_key_from_two_uint128():
    """Two known uint128 values → correct 32-byte AES key."""
    high = 0xAAAA1111222233334444555566667777
    low = 0xBBBB1111222233334444555566668888
    key = reconstruct_key(high, low)
    assert len(key) == 32
    assert key[:16] == high.to_bytes(16, "big")
    assert key[16:] == low.to_bytes(16, "big")


def test_split_key_roundtrip():
    """split → reconstruct is identity."""
    original = bytes(range(32))
    high, low = split_key_for_cofhe(original)
    restored = reconstruct_key(high, low)
    assert restored == original


def test_format_output_key_handle():
    """Formats two handles as concatenated hex."""
    h1, h2 = 0x1234, 0x5678
    result = format_output_key_handle(h1, h2)
    assert result.startswith("0x")
    hex_part = result[2:]
    assert len(hex_part) == 128  # 2 x 32 bytes x 2 hex chars
    assert hex_part[:64] == h1.to_bytes(32, "big").hex()
    assert hex_part[64:] == h2.to_bytes(32, "big").hex()


# ==================================================================
# Mock CoFHE client (updated interface)
# ==================================================================


def test_mock_cofhe_decrypt_returns_int():
    cofhe = MockCoFHEClient()
    val = cofhe.decrypt(12345)
    assert isinstance(val, int)
    assert val == cofhe.decrypt(99999)  # same fixed key


def test_mock_cofhe_encrypt_returns_int():
    cofhe = MockCoFHEClient()
    h = cofhe.encrypt(42)
    assert isinstance(h, int)
    assert h != cofhe.encrypt(42)  # counter increments


# ==================================================================
# CoFHE factory
# ==================================================================


def test_factory_returns_mock_by_default():
    from blindference_node.config import Config
    config = Config()
    client = get_cofhe_client(config, "0x" + "aa" * 32)
    assert isinstance(client, MockCoFHEClient)


def test_factory_returns_python_client():
    from blindference_node.config import Config
    config = Config(cofhe_mode="python")
    client = get_cofhe_client(config, "0x" + "aa" * 32)
    assert isinstance(client, CoFHERealClient)


def test_factory_returns_bridge_client():
    from blindference_node.config import Config
    config = Config(cofhe_mode="bridge")
    client = get_cofhe_client(config, "0x" + "aa" * 32)
    assert isinstance(client, CoFHEBridgeClient)


# ==================================================================
# CoFHERealClient — permit generation
# ==================================================================


def test_real_client_creates_permit():
    """CoFHERealClient._ensure_permit generates a valid EIP-712 permit."""
    client = CoFHERealClient(
        "0x" + "ac" * 32, "http://localhost:9999", chain_id=421614
    )
    permit = client._ensure_permit()
    assert permit.issuer.startswith("0x")
    assert len(permit.issuer) == 42
    assert permit.expiration > 0
    assert permit.sealing_public_hex.startswith("0x")
    assert len(permit.sealing_public_hex) == 66  # 0x + 32 bytes
    assert permit.signature.startswith("0x")
    assert permit.sealing_private_key is not None


def test_real_client_permit_caching():
    """Permit is cached and reused within its validity window."""
    client = CoFHERealClient(
        "0x" + "ac" * 32, "http://localhost:9999"
    )
    p1 = client._ensure_permit()
    p2 = client._ensure_permit()
    assert p1 is p2  # same object reference — cached


# ==================================================================
# CoFHERealClient — decrypt with mock server
# ==================================================================


def test_unseal_roundtrip():
    """_unseal correctly decrypts an ECIES-sealed value."""
    from blindference_node.crypto import _unseal
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    expected = 0xCAFEBABEDEADBEEFC0FFEE1234567890
    sealing_sk = X25519PrivateKey.generate()
    sealing_pk = sealing_sk.public_key()

    # Encrypt (simulate CoFHE server)
    eph = X25519PrivateKey.generate()
    eph_pub = eph.public_key().public_bytes_raw()
    shared = eph.exchange(sealing_pk)
    hkdf = HKDF(algorithm=SHA256(), length=32, salt=None, info=b"CoFHE seal")
    aes_key = hkdf.derive(shared)
    aesgcm = AESGCM(aes_key)
    iv = b"\x00" * 12
    pt = expected.to_bytes(32, "big")
    ct = aesgcm.encrypt(iv, pt, None)
    sealed = eph_pub + iv + ct

    result = _unseal(sealed, sealing_sk)
    assert result == expected
