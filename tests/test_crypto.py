"""Tests for blindference_node.crypto."""

import pytest

from blindference_node.crypto import (
    MockCoFHEClient,
    decrypt_prompt_blob,
    encrypt_output_blob,
    generate_output_key,
    retrieve_prompt_key,
    store_output_key_for_user,
)


def test_generate_output_key_length():
    key = generate_output_key()
    assert len(key) == 32
    assert key != generate_output_key()  # each call is unique


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


def test_mock_cofhe_decrypt_returns_fixed_key():
    cofhe = MockCoFHEClient()
    key = cofhe.decrypt("any-handle", "any-permit")
    assert len(key) == 32
    # Same key every time
    assert key == cofhe.decrypt("other-handle", "other-permit")


def test_mock_cofhe_encrypt_returns_handle():
    cofhe = MockCoFHEClient()
    handle = cofhe.encrypt_for(b"data", "0xuser")
    assert handle.startswith("0x")


def test_retrieve_prompt_key_uses_mock():
    cofhe = MockCoFHEClient(fixed_key=b"\x01" * 32)
    key = retrieve_prompt_key(cofhe, "job-1", "permit")
    assert key == b"\x01" * 32


def test_store_output_key_returns_handles():
    cofhe = MockCoFHEClient()
    result = store_output_key_for_user(
        cofhe, "job-1", b"\x02" * 32, "0xuser"
    )
    handles = result.split(",")
    assert len(handles) == 2
    assert all(h.startswith("0x") for h in handles)


def test_decrypt_prompt_blob_handles_various_sizes():
    key = generate_output_key()
    for size in [1, 10, 100, 1000, 4096]:
        text = "A" * size
        blob = encrypt_output_blob(text, key)
        assert decrypt_prompt_blob(blob, key) == text
