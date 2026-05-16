# Blindference Node Quickstart

Get your GPU machine registered as a Blindference compute provider in under 10 minutes.

## Prerequisites

- **Python 3.10+** — the node package is a Python CLI application.
- **NVIDIA GPU** with at least 512 MB VRAM (any modern GPU qualifies).
- **`nvidia-smi`** available on your `PATH` (installed with the NVIDIA driver).
- **Fhenix testnet ETH** — for gas fees when registering on‑chain (optional for mock attestation).
- **Outbound HTTPS access** — to the ICL, Fhenix RPC, and IPFS gateway.

## Installation

```bash
pip install blindference-node
```

For GPU‑accelerated inference (optional):
```bash
pip install "blindference-node[gpu]"
```

## Initialization

Run the `init` command. It detects your GPU, generates (or imports) an Ethereum wallet, performs a mock attestation, and saves configuration.

### Interactive mode

```bash
blindference-node init
```

You will be prompted to:
1. Create a new wallet or import an existing private key.
2. Set an encryption password for the keystore.
3. Confirm the detected GPU tier and supported models.
4. Optionally register on‑chain (requires testnet ETH).

### Non‑interactive mode (scripts / CI)

```bash
export BLF_PRIVATE_KEY="0xYourPrivateKey"
export BLF_KEY_PASSWORD="your-password"
export BLF_STAKE_AMOUNT="0"
blindference-node init --non-interactive
```

The config file is written to `~/.blindference/config.json`.

## Running the Node

```bash
blindference-node run
```

The daemon starts three concurrent loops:

| Loop | Interval | Purpose |
|---|---|---|
| Heartbeat | 60 s | Keep the node visible on‑chain / ICL |
| Attestation watchdog | 10 min | Re‑attest before the certificate expires |
| Assignment poller | 5 s | Fetch pending jobs and execute them |

Expected log output:

```
[2026-05-16T12:00:00] [INFO   ] [0xf39Fd6e5] Daemon starting …
[2026-05-16T12:00:00] [INFO   ] [0xf39Fd6e5]   Address : 0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266
[2026-05-16T12:00:00] [INFO   ] [0xf39Fd6e5]   Tier    : 0
[2026-05-16T12:00:00] [INFO   ] [0xf39Fd6e5]   Models  : qwen2.5-7b
[2026-05-16T12:00:05] [DEBUG  ] [0xf39Fd6e5] No pending assignments
```

Press `Ctrl+C` to gracefully shut down the daemon.

## Checking Status

```bash
blindference-node status
```

Displays node address, tier, stake, attestation validity, and recent job history.

## Troubleshooting

| Problem | Solution |
|---|---|
| `nvidia-smi not found` | Install the NVIDIA driver. |
| `Could not reach ICL` | Check your network; set `BLF_ICL_ENDPOINT` to override. |
| `Attestation certificate expired` | Run `blindference-node attest` to re‑attest. |
| `No node configured` | Run `blindference-node init` first. |
| `BLF_KEY_PASSWORD is empty` | Set the env var or run in interactive mode. |
| `VRAM requirement not met` | Your GPU has too little VRAM; minimum 512 MB required. |

## Next Steps

- [Hardware Requirements](./hardware.md) — GPU tier details and TEE support.
- [Attestation Guide](./attestation.md) — How attestation works and future backends.
- [Slashing & Recovery](./slashing.md) — What can get you slashed and how to recover.
