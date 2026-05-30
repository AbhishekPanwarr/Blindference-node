# Blindference Node

[![PyPI version](https://badge.fury.io/py/blindference-node.svg)](https://pypi.org/project/blindference-node/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Node.js 18+](https://img.shields.io/badge/node.js-18+-green.svg)](https://nodejs.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Confidential inference worker for the Blindference decentralized AI execution network.**

Run encrypted inference jobs, earn fees, and help build a private, verifiable, and economically accountable AI execution layer on Arbitrum Sepolia.

---

## What It Does

Blindference Node is the runtime that executes confidential inference tasks assigned by the Inference Coordination Layer (ICL). Each node:

- **Attests** its identity and capabilities to the ICL (mock TEE for tier 0, TPM/TEE for higher tiers)
- **Heartbeats** every 60 seconds to prove liveness (ICL) and every 10 days on-chain
- **Polls** for pending job assignments every 5 seconds
- **Decrypts** encrypted prompts via CoFHE threshold FHE under strict ACL
- **Executes** inference via Groq Llama 3, Google Gemini, or local vLLM (pluggable backends)
- **Commits** results back to the ICL for quorum consensus
- **Earns** fees for successful task completion

---

## Prerequisites

Blindference Node requires **both** Python and Node.js runtimes:

| Runtime | Minimum Version | Check Command | Why Required |
|---------|----------------|---------------|--------------|
| **Python** | 3.10+ | `python --version` | CLI, wallet management, inference backends |
| **Node.js** | 18+ | `node --version` | CoFHE bridge (`cofhe_bridge.mjs`) |
| **npm** | bundled with Node | `npm --version` | Installing CoFHE SDK and viem dependencies |

### Verify Your Environment

```bash
# Check Python
python --version   # Should print 3.10.x or higher

# Check Node.js
node --version     # Should print v18.x.x or higher
npm --version      # Should print 10.x.x or higher
```

If either is missing:
- **Python**: [python.org/downloads](https://www.python.org/downloads/) or `apt install python3 python3-pip`
- **Node.js**: [nodejs.org](https://nodejs.org/) or `apt install nodejs npm`

---

## Quick Start (First-Time Setup)

### 1. Clone the Repository

```bash
git clone https://github.com/AbhishekPanwarr/Blindference-node.git
cd Blindference-node
```

> **Why clone instead of `pip install`?**  
> The CoFHE bridge (`cofhe_bridge.mjs`) depends on Node.js packages (`@cofhe/sdk`, `viem`) that cannot be bundled in a Python wheel. Cloning gives you the full source including the `package.json` that declares these dependencies.

### 2. Install Node.js Dependencies (CoFHE Bridge)

```bash
npm install
```

This installs:
- `@cofhe/sdk` — Fhenix CoFHE client for confidential decryption
- `viem` — Ethereum client for on-chain interactions

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Install the CLI Package

```bash
pip install -e .
```

This creates the `blindference-node` command globally in your environment.

### 5. Verify Installation

```bash
blindference-node --help
```

You should see the CLI help output with commands: `init`, `attest`, `run`, `status`, `staking`, `models`, etc.

---

## Node Lifecycle

### Step 1: Initialize (`blindference-node init`)

```bash
blindference-node init
```

This will:
1. Detect GPU capabilities (or default to cloud inference)
2. Auto-detect cloud API keys (Groq / Gemini) from environment
3. Generate an encrypted Ethereum wallet keystore
4. Save configuration to `./config.json` (or `~/.blindference/config.json` if `BLF_CONFIG_DIR` is set)

**Non-interactive mode:**

```bash
export BLF_PRIVATE_KEY=0x...
export BLF_KEY_PASSWORD=secure_password
blindference-node init
```

### Step 2: Attest (`blindference-node attest`)

```bash
# Interactive attestation (choose mock or TEE)
blindference-node attest

# Or skip interactive menu and use mock directly (for development)
blindference-node attest --mock

# With custom development key
blindference-node attest --mock --tee-key mydevkey
```

After ICL attestation, optionally register on-chain with gas estimation.

### Step 3: Stake BLIND Tokens (`blindference-node staking stake`)

Nodes must stake at least **1000 BLIND** to participate in inference quorums. Staking provides economic security — stake is slashed if a node produces incorrect output or times out.

```bash
# Stake 1000 BLIND (minimum)
blindference-node staking stake 1000

# Check your stake status
blindference-node staking status

# Initiate unstake (starts 96h unbonding)
blindference-node staking unstake

# Complete unstake after unbonding period
blindference-node staking withdraw
```

**Staking Economics:**
- Minimum stake: **1000 BLIND**
- Unbonding period: **96 hours**
- Reward per job: **1 BLIND** (60% leader, 20% each verifier)
- Slashing: **3 consecutive failures** → entire stake hard-slashed on-chain

### Step 4: Run the Daemon (`blindference-node run`)

```bash
blindference-node run
```

The daemon starts four concurrent loops:

| Loop | Frequency | Purpose |
|------|-----------|---------|
| **ICL Heartbeat** | Every 60s | Proves liveness to ICL (free REST call) |
| **On-Chain Heartbeat** | Every 10 days | Proves liveness to NodeRegistry (gas tx) |
| **Attestation Watchdog** | Every 10min | Auto-re-attests if certificate expires within 6h |
| **Assignment Poller** | Every 5s | Polls ICL for pending inference jobs |

---

## Environment Variables

All configuration can be overridden via environment variables prefixed with `BLF_`:

| Variable | Type | Description | Example |
|----------|------|-------------|---------|
| `BLF_PRIVATE_KEY` | string | Operator wallet private key (hex) | `0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80` |
| `BLF_KEY_PASSWORD` | string | Keystore decryption password | `secure_password` |
| `BLF_ICL_ENDPOINT` | string | ICL base URL | `https://icl.blindference.xyz` |
| `BLF_RPC_URL` | string | Arbitrum Sepolia RPC endpoint | `https://arb-sepolia.g.alchemy.com/v2/YOUR_KEY` |
| `BLF_COFHE_ENDPOINT` | string | CoFHE/EVM RPC endpoint (usually same as RPC) | `https://arb-sepolia.g.alchemy.com/v2/YOUR_KEY` |
| `BLF_COFHE_CHAIN_ID` | int | Chain ID for CoFHE | `421614` |
| `BLF_COFHE_MODE` | string | `bridge` (TypeScript subprocess) or `python` (HTTP) | `bridge` |
| `GROQ_API_KEY` | string | Enables Groq cloud backend | `gsk_...` |
| `GOOGLE_API_KEY` | string | Enables Gemini cloud backend | `AIza...` |
| `BLF_LOG_LEVEL` | string | Logging verbosity | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

### Critical: Set Real RPC Endpoints

The default Alchemy URL `https://arb-sepolia.g.alchemy.com/v2/demo` is a **placeholder** and will fail:

```bash
# Get a free key at https://dashboard.alchemy.com/apps
export BLF_RPC_URL='https://arb-sepolia.g.alchemy.com/v2/YOUR_REAL_KEY'
export BLF_COFHE_URL='https://arb-sepolia.g.alchemy.com/v2/YOUR_REAL_KEY'
```

Without a real RPC endpoint, the node will crash during CoFHE decryption with:
```
Invalid CoFHE RPC URL: https://arb-sepolia.g.alchemy.com/v2/demo
The default Alchemy key is a placeholder. Set a real key.
```

---

## Model Backends

Blindference Node uses a **pluggable backend registry** to support multiple inference providers.

### Built-in Backends

| Backend | Description | Requirements | Model IDs |
|---------|-------------|--------------|-----------|
| `vllm` | Local GPU inference | NVIDIA GPU + `vllm` package | `facebook/opt-125m` |
| `groq` | Groq cloud API | `GROQ_API_KEY` env var | `groq:llama-3.3-70b-versatile` |
| `gemini` | Google Gemini REST API | `GOOGLE_API_KEY` env var | `gemini:gemini-2.5-flash` |
| `mock` | Deterministic SHA-256 fallback | Always available | `*` (universal fallback) |

### Custom Backends

```python
from blindference_node.models.base import ModelBackend

class MyBackend(ModelBackend):
    def name(self) -> str: return "my-backend"
    def is_available(self) -> bool: return True
    def supported_models(self) -> list[str]: return ["my-model"]
    def run(self, model_id: str, prompt: str) -> str: return "result"
```

Register via CLI:

```bash
blindference-node models add my_package.backends:MyBackend
```

---

## Commands Reference

| Command | Description | Status |
|---------|-------------|--------|
| `init` | Initialize node — wallet, GPU detection, save config | Ready |
| `attest` | Attest node with ICL (mock / TEE) and optionally register on-chain | Ready |
| `run` | Start daemon — heartbeat, watchdog, job polling & execution | Ready |
| `status` | Show node status — address, tier, models, cert expiry | Ready |
| `staking stake` | Stake BLIND tokens to join inference quorums | Ready |
| `staking unstake` | Initiate unstake (starts 96h unbonding) | Ready |
| `staking withdraw` | Complete withdrawal after unbonding period | Ready |
| `staking status` | Show BLIND stake status and failure count | Ready |
| `models list` | List all registered inference backends and availability | Ready |
| `models test` | Test a specific backend with a prompt | Ready |
| `models add` | Register a custom backend from a dotted Python path | Ready |
| `test-determinism` | Run GPU determinism self-test with vLLM or cloud APIs | Ready |
| `jobs list` | List completed jobs and BLIND earnings | Ready |
| `jobs earnings` | Total BLIND earned across all completed jobs | Ready |
| `balance` | Current BLIND token balance | Ready |

---

## Architecture

```mermaid
flowchart TB
    subgraph "Blindference Node"
        DAEMON[Daemon Process]
        HB[ICL Heartbeat<br/>60s]
        ONCHAIN[On-Chain Heartbeat<br/>10 days]
        WD[Attestation Watchdog<br/>10min]
        POLL[Assignment Poller<br/>5s]
        WORKER[Job Worker]
        
        DAEMON --> HB
        DAEMON --> ONCHAIN
        DAEMON --> WD
        DAEMON --> POLL
        POLL -->|dispatch| WORKER
    end
    
    subgraph "External Services"
        ICL[ICL Coordinator]
        COFHE[CoFHE Network]
        IPFS[IPFS Gateway]
        LLM[Groq / Gemini / vLLM]
        CHAIN[Arbitrum Sepolia]
    end
    
    HB -->|POST /internal/heartbeat| ICL
    ONCHAIN -->|NodeRegistry.heartbeat()| CHAIN
    WD -->|GET /internal/challenge| ICL
    WD -->|POST /internal/attestation/verify| ICL
    POLL -->|GET /internal/assignments/{addr}| ICL
    WORKER -->|POST /internal/task/claim| ICL
    WORKER -->|decryptForView| COFHE
    WORKER -->|download blob| IPFS
    WORKER -->|run inference| LLM
    WORKER -->|POST /internal/task/result| ICL
    
    ICL -->|register attestation| CHAIN
```

---

## Configuration

All configuration is stored in `./config.json` (or `~/.blindference/config.json` if `BLF_CONFIG_DIR` is set) and can be overridden via environment variables prefixed with `BLF_`.

### Default Config

```json
{
  "node_address": "0x...",
  "keystore_path": "./keystore.json",
  "tier": 0,
  "supported_model_ids": ["facebook/opt-125m"],
  "custom_backends": [],
  "attestation_backend": "mock",
  "icl_endpoint": "https://icl.blindference.xyz",
  "rpc_url": "",
  "ipfs_gateway": "https://node.lighthouse.storage",
  "model_cache_dir": "./models",
  "log_level": "INFO",
  "network": "arbitrum_sepolia",
  "attestation_cert_hash": "",
  "attestation_expiry": 0,
  "registered_on_chain": false,
  "stake_amount_wei": 0,
  "cofhe_mode": "bridge",
  "cofhe_endpoint": "",
  "cofhe_chain_id": 421614,
  "skip_output_key_storage": false
}
```

### CoFHE Modes

**`bridge` (default)**: Spawns a TypeScript subprocess via `@cofhe/sdk/node` for CoFHE operations. More reliable, handles SDK lifecycle correctly.

**`python` (alternative)**: Direct HTTP calls to CoFHE endpoints. Lighter weight but requires manual session management.

---

## Troubleshooting

### "Invalid CoFHE RPC URL" error

**Symptom:**
```
Invalid CoFHE RPC URL: https://arb-sepolia.g.alchemy.com/v2/demo
The default Alchemy key is a placeholder. Set a real key.
```

**Fix:**
```bash
export BLF_RPC_URL='https://arb-sepolia.g.alchemy.com/v2/YOUR_REAL_KEY'
export BLF_COFHE_ENDPOINT='https://arb-sepolia.g.alchemy.com/v2/YOUR_REAL_KEY'
```

Get a free key at [alchemy.com](https://dashboard.alchemy.com/apps).

### "CoFHE bridge process exited with code 1"

**Symptom:** Node crashes during job execution with bridge exit code 1.

**Fix:** Ensure you ran `npm install` in the repo root before starting the node. The bridge requires `@cofhe/sdk` and `viem` Node.js packages.

```bash
cd /path/to/Blindference-node
npm install
```

### "Module not found: @cofhe/sdk"

**Symptom:**
```
Error [ERR_MODULE_NOT_FOUND]: Cannot find package '@cofhe/sdk'
```

**Fix:** You skipped `npm install`. Run it now:
```bash
npm install
```

### "Permission denied: blindference-node"

**Symptom:** Command not found after `pip install -e .`.

**Fix:** Ensure your Python environment's `bin/` directory is in `PATH`, or use the full path:
```bash
python -m blindference_node.cli --help
```

---

## PyPI Package

A PyPI package is available for convenience:

```bash
pip install blindference-node
```

> **Note:** The PyPI wheel includes the Python CLI but does **not** bundle Node.js dependencies. After `pip install`, you must still run `npm install` in the package directory to install the CoFHE bridge dependencies. For first-time setup, **cloning the repository is recommended** (see Quick Start above).

---

## Development

### Setup

```bash
# Clone repository
git clone https://github.com/AbhishekPanwarr/Blindference-node.git
cd Blindference-node

# Install Node.js dependencies
npm install

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt
pip install -e ".[dev]"

# Run tests
pytest tests/ -v
```

### Project Structure

```text
Blindference-node/
├── blindference_node/          # Main package
│   ├── __init__.py
│   ├── cli.py                  # CLI entry points (init, attest, run, status, models)
│   ├── node_loop.py            # Daemon with heartbeat, watchdog, poller
│   ├── job_handler.py          # Task execution logic
│   ├── crypto.py               # CoFHE client, AES blob encryption/decryption
│   ├── icl_client.py           # ICL REST API client
│   ├── wallet.py               # Ethereum wallet generation and loading
│   ├── registry.py             # On-chain registration and heartbeat
│   ├── config.py               # Configuration management
│   ├── attestation/            # Attestation backends (mock, TPM, TEE)
│   ├── models/                 # Pluggable inference backends
│   │   ├── base.py
│   │   ├── vllm_backend.py
│   │   ├── groq_backend.py
│   │   ├── gemini_backend.py
│   │   ├── mock_backend.py
│   │   └── registry.py
│   ├── backend_loader.py       # Dynamic backend loading
│   └── scripts/                # TypeScript CoFHE bridge
│       └── cofhe_bridge.mjs
├── tests/                      # Test suite
│   ├── test_crypto.py
│   ├── test_job_handler.py
│   ├── test_node_loop.py
│   ├── test_icl_client.py
│   ├── test_registry.py
│   ├── test_e2e.py
│   └── test_wallet.py
├── contracts/                  # Solidity contract ABIs
├── package.json                # Node.js dependencies (CoFHE SDK, viem)
├── pyproject.toml              # Package configuration
├── requirements.txt            # Python dependencies
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Container image
└── README.md                   # This file
```

### Docker

```bash
# Build image
docker build -t blindference-node .

# Run container
docker run -d \
  --name blindference-node \
  -e BLF_KEY_PASSWORD=secure_password \
  -e BLF_ICL_ENDPOINT=https://icl.blindference.xyz \
  -e BLF_RPC_URL=https://arb-sepolia.g.alchemy.com/v2/YOUR_KEY \
  -v /host/config:/root/.blindference \
  blindference-node run
```

---

## Security Model

### Tier 0 (Mock Attestation)

- Software-only attestation with no hardware trust
- Quote: HMAC-SHA256 of nonce + runtime code hash
- **For development only** — nodes can be impersonated

### Tier 1 (TPM 2.0)

- TPM-backed attestation with measured boot
- Hardware-bound identity
- Requires TPM 2.0 chip

### Tier 2 (TEE / SGX / TDX)

- Intel SGX or AMD SEV enclave attestation
- Confidential computing — code and data encrypted in memory
- Remote attestation verified by ICL against manufacturer quoting enclaves

### Slashing Conditions

Nodes may be slashed for:
- **Failed attestation**: Missing or expired certificate
- **Missed heartbeat**: No ICL heartbeat within 5 minutes
- **Bad inference**: Verifier consensus shows wrong result
- **Timeout**: Failed to submit result within execution window

---

## Consensus Calibration Feedback

Every accepted inference job feeds into a long-term calibration loop that improves quorum accuracy over time:

| Signal | Source | Impact |
|--------|--------|--------|
| **Thumbs Up** | User decrypts output, votes "accurate" | Increases confidence weight for leader's model provider |
| **Thumbs Down** | User decrypts output, votes "not accurate" | Flags potential false positives; triggers threshold review |
| **Dispute Override** | User overrides quorum rejection | Signals verifier pool may be too strict |
| **Verdict Mismatch** | Verifiers disagree with accepted leader | Reduces reputation of outlier verifier |

Nodes benefit from accurate calibration — a well-tuned quorum means fewer false rejections (more jobs accepted, more fees earned) and fewer false acceptions (less slashing risk).

---

## Documentation

- [Quickstart Guide](https://docs.blindference.xyz/compute/quickstart) — Step-by-step first node setup
- [Attestation Guide](https://docs.blindference.xyz/compute/attestation) — Mock, TPM, and TEE attestation
- [Configuration](https://docs.blindference.xyz/compute/configuration) — All config options and env vars
- [Model Backends](https://docs.blindference.xyz/compute/backends) — Pluggable backend system
- [Rewards & Slashing](https://docs.blindference.xyz/compute/rewards) — How nodes earn and what gets them slashed
- [Troubleshooting](https://docs.blindference.xyz/compute/troubleshooting) — Common issues and fixes

---

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

---

## License

MIT License — see [LICENSE](./LICENSE) for details.

---

## Support

- **Docs**: [docs.blindference.xyz](https://docs.blindference.xyz)
- **Discord**: [Blindference Community](https://discord.gg/blindference)
- **Twitter**: [@blindference](https://twitter.com/blindference)
- **Issues**: [GitHub Issues](https://github.com/AbhishekPanwarr/Blindference-node/issues)
