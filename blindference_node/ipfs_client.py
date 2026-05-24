"""IPFS client — upload / download encrypted blobs."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List

import aiohttp

# Fallback public gateways (tried in order after the configured primary)
_FALLBACK_GATEWAYS: List[str] = [
    "https://gateway.pinata.cloud/ipfs",
    "https://cloudflare-ipfs.com/ipfs",
    "https://ipfs.io/ipfs",
    "https://gateway.ipfs.io/ipfs",
]


def _build_gateway_url(gateway: str, cid: str) -> str:
    """Build a full download URL avoiding double ``/ipfs/`` paths."""
    gw = gateway.rstrip("/")
    if gw.endswith("/ipfs"):
        return f"{gw}/{cid}"
    return f"{gw}/ipfs/{cid}"


class IPFSClient:
    """Async IPFS client with multi-gateway fallback.

    Uploads go through the Pinata pinning API.  Downloads try the
    configured *gateway_url* first, then rotate through a list of
    public fallback gateways before giving up.

    Args:
        gateway_url: Primary IPFS gateway base URL
            (e.g. ``https://node.lighthouse.storage``).
    """

    def __init__(self, gateway_url: str) -> None:
        self._primary = gateway_url.rstrip("/")

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

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
                "https://api.pinata.cloud/pinning/pinFileToIPFS",
                headers={"Authorization": f"Bearer {jwt}"},
                data=form,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (401, 403):
                    text = await resp.text()
                    raise RuntimeError(
                        f"Pinata authentication failed ({resp.status}): {text}. "
                        "Your JWT may be revoked or expired. Generate a new key at "
                        "https://pinata.cloud/keys and update BLF_IPFS_UPLOAD_JWT."
                    )
                if resp.status >= 400:
                    text = await resp.text()
                    raise RuntimeError(f"Pinata upload failed ({resp.status}): {text}")
                result = await resp.json()
                # Classic Pinata returns IpfsHash directly; v3 wraps in {"data": {"cid": ...}}
                cid = result.get("IpfsHash") or result.get("data", {}).get("cid")
                if not cid:
                    raise RuntimeError(f"Pinata upload returned unexpected response: {result}")
                return str(cid)

    # ------------------------------------------------------------------
    # Download with fallback
    # ------------------------------------------------------------------

    async def download(self, cid: str) -> bytes:
        """Download a blob from IPFS by CID across multiple gateways.

        Tries the primary gateway first, then rotates through fallback
        public gateways.  Each attempt uses a 15-second timeout so the
        total budget across all gateways is ~60 s.

        Returns:
            The raw bytes.

        Raises:
            RuntimeError: if every gateway fails or times out.
        """
        # Build ordered list of unique gateways to try
        gateways = [self._primary]
        for fallback in _FALLBACK_GATEWAYS:
            if fallback.rstrip("/") != self._primary.rstrip("/"):
                gateways.append(fallback)

        per_gateway_timeout = aiohttp.ClientTimeout(
            total=15,
            connect=5,
            sock_read=10,
        )

        last_error: Exception | None = None
        for idx, gateway in enumerate(gateways):
            url = _build_gateway_url(gateway, cid)
            try:
                async with aiohttp.ClientSession(timeout=per_gateway_timeout) as session:
                    async with session.get(url) as resp:
                        if resp.status >= 400:
                            text = await resp.text()
                            raise RuntimeError(
                                f"HTTP {resp.status} from {gateway}: {text[:200]}"
                            )
                        return await resp.read()
            except asyncio.TimeoutError:
                last_error = RuntimeError(
                    f"Gateway {gateway} timed out after 15s for CID={cid}"
                )
                logger = logging.getLogger("blindference-node.ipfs")
                logger.debug("Gateway %d/%d timed out: %s", idx + 1, len(gateways), gateway)
            except aiohttp.ClientConnectorError as exc:
                last_error = RuntimeError(
                    f"Connection error from {gateway} for CID={cid}: {exc}"
                )
                logger = logging.getLogger("blindference-node.ipfs")
                logger.debug("Gateway %d/%d connection error: %s", idx + 1, len(gateways), gateway)
            except aiohttp.ClientError as exc:
                last_error = RuntimeError(
                    f"Client error from {gateway} for CID={cid}: {exc}"
                )
                logger = logging.getLogger("blindference-node.ipfs")
                logger.debug("Gateway %d/%d client error: %s", idx + 1, len(gateways), gateway)
            except RuntimeError as exc:
                last_error = exc
                logger = logging.getLogger("blindference-node.ipfs")
                logger.debug("Gateway %d/%d HTTP error: %s", idx + 1, len(gateways), exc)

        # All gateways exhausted
        raise RuntimeError(
            f"IPFS download failed for CID={cid} after trying {len(gateways)} gateways. "
            f"Last error: {last_error}"
        )
