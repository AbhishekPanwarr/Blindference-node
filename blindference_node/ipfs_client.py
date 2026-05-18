"""IPFS client — upload / download encrypted blobs."""

from __future__ import annotations

import asyncio
import os

import aiohttp


class IPFSClient:
    """Async IPFS client backed by the Lighthouse gateway.

    Args:
        gateway_url: Base URL of the IPFS gateway (e.g. ``https://node.lighthouse.storage``).
    """

    def __init__(self, gateway_url: str) -> None:
        self._gateway = gateway_url.rstrip("/")

    async def upload(self, data: bytes) -> str:
        """Upload *data* to IPFS via Pinata pinning service.

        Returns a real IPFS CID when ``BLF_IPFS_UPLOAD_JWT`` is set.
        Falls back to a mock CID for local testing.
        """
        jwt = os.environ.get("BLF_IPFS_UPLOAD_JWT")
        if not jwt:
            import hashlib
            return "Qm" + hashlib.sha256(data).hexdigest()[:44]

        async with aiohttp.ClientSession() as session:
            form = aiohttp.FormData()
            form.add_field("file", data, filename="blindference-output.bin")
            async with session.post(
                "https://uploads.pinata.cloud/v3/files",
                headers={"Authorization": f"Bearer {jwt}"},
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"Pinata upload failed ({resp.status}): {text}")
                result = await resp.json()
                return str(result["data"]["cid"])

    async def download(self, cid: str) -> bytes:
        """Download a blob from IPFS by CID.

        Returns:
            The raw bytes.

        Raises:
            RuntimeError: if the download fails.
        """
        url = f"{self._gateway}/ipfs/{cid}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 400:
                    raise RuntimeError(
                        f"IPFS download failed: {resp.status} {await resp.text()}"
                    )
                return await resp.read()
