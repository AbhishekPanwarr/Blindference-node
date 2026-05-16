"""Tests for blindference_node.crypto."""

import pytest

from blindference_node.crypto import (
    MockCoFHEClient,
    decrypt_prompt_blob,
    encrypt_output_blob,
    format_output_key_handle,
    generate_output_key,
    reconstruct_key,
    split_key_for_cofhe,
)


def test_generate_output_key_length():
    key = generate_output_key()
    assert len(key) == 32
    assert key != generate_output_key()


def test_aes_encrypt_decrypt_roundtrip():
    key = generate_output_key()
    text = "Hello, Blindference! This is a confidential inference output."
    blob = encrypt_output_blob(text, key)
    result = decrypt_prompt_blob(blob, key)
    assert result == text


def test_aes_wrong_key_fails():
    key1 = generate_output_key()
    key2 = generate_output_key()
    blob = encrypt_output_blob("secret", key1)
    with pytest.raises(Exception):
        decrypt_prompt_blob(blob, key2)


def test_mock_cofhe_decrypt_returns_int():
    cofhe = MockCoFHEClient()
    val = cofhe.decrypt(12345)
    assert isinstance(val, int)
    assert val == cofhe.decrypt(99999)


def test_mock_cofhe_encrypt_returns_int():
    cofhe = MockCoFHEClient()
    h = cofhe.encrypt(42)
    assert isinstance(h, int)


def test_reconstruct_key():
    high = 0x1234
    low = 0x5678
    key = reconstruct_key(high, low)
    assert len(key) == 32
    assert key[:16] == high.to_bytes(16, "big")
    assert key[16:] == low.to_bytes(16, "big")


def test_split_key_roundtrip():
    original = bytes(range(32))
    high, low = split_key_for_cofhe(original)
    restored = reconstruct_key(high, low)
    assert restored == original


def test_format_output_key_handle():
    result = format_output_key_handle(0xAAAA, 0xBBBB)
    assert result.startswith("0x")
    assert len(result) == 130
