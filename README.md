# Blindference Node

**Version 0.2.0** — Confidential inference worker for agentic AI.

Register your GPU machine as a compute provider in the Blindference network. Run encrypted inference jobs, earn fees, and help build a private, verifiable, and economically accountable AI execution layer.

## Install

```bash
pip install blindference-node
```

For GPU‑accelerated inference (optional):
```bash
pip install "blindference-node[gpu]"
```

## Quick Start

```bash
blindference-node init   # detect GPU, create wallet, attest
blindference-node run    # start the node daemon
```

This detects your GPU, generates a wallet, runs a determinism self‑test, performs mock attestation, and starts the daemon — all in under 5 minutes.

## Commands

| Command | Description |
|---|---|
| `init` | Initialize the node — wallet, GPU detection, attestation, on‑chain registration |
| `run` | Start the daemon — heartbeat, attestation watchdog, job polling & execution |
| `status` | Show node state — address, tier, stake, recent jobs |
| `attest` | Manually trigger re‑attestation |
| `withdraw` | Initiate stake unbonding |

## Requirements

- Python 3.10+
- NVIDIA GPU with at least 512 MB VRAM (mock inference works without GPU)
- `nvidia-smi` available on PATH
- Outbound HTTPS access to ICL, Fhenix RPC, and IPFS gateway

## Documentation

- [Quickstart Guide](./docs/quickstart.md)
- [Hardware Requirements](./docs/hardware.md)
- [Attestation Guide](./docs/attestation.md)
- [Slashing & Recovery](./docs/slashing.md)

## License

MIT
