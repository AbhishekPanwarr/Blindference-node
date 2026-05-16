"""Tests for blindference_node.ipfs_client."""

import pytest

from blindference_node.ipfs_client import IPFSClient


@pytest.mark.asyncio
async def test_upload_returns_cid():
    client = IPFSClient("https://node.lighthouse.storage")
    cid = await client.upload(b"test data for IPFS")
    assert cid.startswith("Qm")
    assert len(cid) >= 46  # SHA-256 CID v0


@pytest.mark.asyncio
async def test_upload_is_deterministic_per_content():
    client = IPFSClient("https://node.lighthouse.storage")
    cid1 = await client.upload(b"same content")
    cid2 = await client.upload(b"same content")
    assert cid1 == cid2


@pytest.mark.asyncio
async def test_upload_different_content_different_cid():
    client = IPFSClient("https://node.lighthouse.storage")
    cid1 = await client.upload(b"content A")
    cid2 = await client.upload(b"content B")
    assert cid1 != cid2
