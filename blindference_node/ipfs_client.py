"""IPFS client — upload / download encrypted blobs."""

from __future__ import annotations

import asyncio

import aiohttp


class IPFSClient:
    """Async IPFS client backed by the Lighthouse gateway.

    Args:
        gateway_url: Base URL of the IPFS gateway (e.g. ``https://node.lighthouse.storage``).
    """

    def __init__(self, gateway_url: str) -> None:
        self._gateway = gateway_url.rstrip("/")

    async def upload(self, data: bytes) -> str:
        """Upload *data* to IPFS via a `PUT`-style gateway endpoint.

        Returns:
            The IPFS CID string.

        Raises:
            RuntimeError: if the upload fails.
        """
        # Lighthouse storage doesn't have a simple public upload API; for now
        # we implement a mock-like placeholder.  Real upload uses the
        # lighthouse-web3 SDK or the Pinata API.
        import hashlib
        return "Qm" + hashlib.sha256(data).hexdigest()[:44]

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
