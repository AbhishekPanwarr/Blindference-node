# Blindference Node — Complete Context Transfer Document

> **Purpose**: This document is a self-contained handoff for any future LLM or engineer picking up the `blindference-node` package. All architecture, APIs, data models, code paths, known bugs, and workarounds are embedded here.

---

## 1. What This Package Is

`blindference-node` is the **standalone compute node runtime** for the Blindference confidential AI inference network. Nodes execute encrypted inference tasks assigned by the Inference Coordination Layer (ICL), commit results for quorum consensus, and earn fees for honest computation.

**PyPI**: https://pypi.org/project/blindference-node/  
**Current version**: 0.3.2  
**Source**: https://github.com/AbhishekPanwarr/Blindference-node

**Key features**:
- Attestation (mock/TEE/TPM) to the ICL
- Automatic heartbeat (ICL every 60s, on-chain every 10 days)
- Job polling and execution with concurrency limits
- CoFHE (FHE) decryption via TypeScript bridge (`@cofhe/sdk/node`)
- IPFS blob download/upload
- Pluggable inference backends: Groq Llama 3.3 70B, Google Gemini 2.5 Flash, local vLLM
- Automatic re-attestation when certificate expires or ICL resets
- On-chain registration with gas estimation

---

## 2. Architecture

### 2.1 High-Level Node Lifecycle

```
┌─────────────────┐     ┌───────────────┐     ┌─────────────────┐
│      init       │────▶│    attest     │────▶│       run       │
│  (wallet+GPU)   │     │  (ICL cert)   │     │  (daemon loops) │
└─────────────────┘     └───────────────┘     └─────────────────┘
                                                        │
                       ┌────────────────────────────────┼────────────────────────────────┐
                       │                                │                                │
                       ▼                                ▼                                ▼
                ┌─────────────┐                 ┌─────────────┐                 ┌─────────────┐
                │  Heartbeat  │                 │   Poller    │                 │  Watchdog   │
                │   60/864000s│                 │   5s        │                 │   10min     │
                └─────────────┘                 └─────────────┘                 └─────────────┘
                                                        │
                                                        ▼
                                               ┌─────────────┐
                                               │  Job Worker │
                                               │ (max 2 conc)│
                                               └─────────────┘
                                                        │
                       ┌────────────────────────────────┼────────────────────────────────┐
                       │                                │                                │
                       ▼                                ▼                                ▼
                ┌─────────────┐                 ┌─────────────┐                 ┌─────────────┐
                │    CoFHE    │                 │    IPFS     │                 │    LLM      │
                │  Decrypt    │                 │  Blob I/O   │                 │  Inference  │
                └─────────────┘                 └─────────────┘                 └─────────────┘
```

### 2.2 Daemon Loops

The `run` command starts 3 concurrent asyncio tasks:

| Loop | Frequency | Purpose | On Failure |
|------|-----------|---------|------------|
| **ICL Heartbeat** | 60s | `POST /internal/heartbeat` — proves liveness to ICL (free REST call) | Logged warning, continues |
| **On-Chain Heartbeat** | 10 days (864,000s) | `NodeRegistry.heartbeat()` — proves liveness on-chain (gas tx) | Logged warning, continues |
| **Attestation Watchdog** | 10min | Checks if cert expires within 6h → auto re-attests | Logged warning, continues |
| **Assignment Poller** | 5s | `GET /internal/assignments/{addr}` → spawns job workers | If ICL returns 401/404 (node unknown), auto re-attests then resumes |

**Concurrency limit**: Max 2 concurrent jobs (`asyncio.Semaphore(2)`). Each job has a hard 5-minute timeout.

---

## 3. Installation

```bash
# From PyPI (recommended)
pip install blindference-node

# With GPU support (local vLLM)
pip install "blindference-node[gpu]"

# From source
git clone https://github.com/AbhishekPanwarr/Blindference-node.git
cd Blindference-node
pip install -e ".[dev]"
```

**Python**: 3.10+  
**OS**: Linux (tested Ubuntu 22.04), macOS  
**GPU** (optional): NVIDIA with CUDA for local vLLM

---

## 4. Quick Start

### 4.1 Environment Variables (CRITICAL)

Create a `.env` file in the project directory or `~/.blindference/.env`:

```bash
# REQUIRED: Arbitrum Sepolia RPC (Alchemy recommended)
# The ICL and all nodes MUST use the same network
BLF_RPC_URL=https://arb-sepolia.g.alchemy.com/v2/YOUR_ALCHEMY_KEY
BLF_COFHE_ENDPOINT=https://arb-sepolia.g.alchemy.com/v2/YOUR_ALCHEMY_KEY

# REQUIRED for cloud inference (pick at least one)
# NO QUOTES around values — the parser strips them, but don't rely on it
GROQ_API_KEY=gsk_YOUR_ACTUAL_GROQ_KEY_WITHOUT_QUOTES
GOOGLE_API_KEY=AIzaYOUR_ACTUAL_GOOGLE_KEY_WITHOUT_QUOTES

# REQUIRED: Keystore password
BLF_KEY_PASSWORD=your_secure_password

# OPTIONAL: Non-interactive init
BLF_PRIVATE_KEY=0xyour_private_key_hex

# OPTIONAL: Override defaults
BLF_ICL_ENDPOINT=https://icl.blindference.xyz
BLF_LOG_LEVEL=INFO
MOCK_ATTESTATION_KEY=weloveblindference
```

**CRITICAL**: Do NOT put quotes around values in `.env` files. While the parser now strips them (bug fix v0.3.2), it's safer to write raw values.

### 4.2 Initialize

```bash
# Interactive (prompts for wallet creation)
blindference-node init

# Non-interactive (uses env vars)
blindference-node init
```

This creates:
- `~/.blindference/keystore.json` — encrypted Ethereum wallet
- `~/.blindference/config.json` — node configuration

### 4.3 Attest

```bash
# Mock attestation (development — default)
blindference-node attest --mock

# With custom mock key
blindference-node attest --mock --tee-key mydevkey

# Interactive (choose mock vs TEE)
blindference-node attest
```

### 4.4 Run

```bash
blindference-node run
```

---

## 5. CLI Commands

| Command | Description | Status |
|---------|-------------|--------|
| `init` | Create wallet, detect GPU, save config | Ready |
| `attest [--mock] [--tee-key KEY]` | Attest with ICL, optionally register on-chain | Ready |
| `run [--log-level LEVEL]` | Start daemon (heartbeat + poller + watchdog) | Ready |
| `status` | Show node address, tier, models, cert expiry | Ready |
| `models list` | Show all backends and availability | Ready |
| `models test [--backend NAME] [--model ID] [--prompt TEXT]` | Test inference backend | Ready |
| `models add DOTTED_PATH` | Register custom backend class | Ready |
| `test-determinism [--model ID] [--prompt TEXT]` | Self-test deterministic output | Ready |
| `jobs list [--limit N]` | List completed jobs and earnings from Payment Service | Ready |
| `jobs claim` | Claim pending earnings (no-op — auto-distributed) | Ready |
| `withdraw` | Stake withdrawal (not implemented) | Stub |

### 5.1 Command Details

#### `init`

```bash
blindference-node init
```

**What it does**:
1. Checks `BLF_PRIVATE_KEY` env var — if present, imports wallet
2. Otherwise prompts: create new wallet or import existing
3. Detects GPU via `nvidia-smi` (NVIDIA) or falls back to CPU
4. Maps VRAM to tier:
   - `≥0.5 GB` → tier 0, supports `facebook/opt-125m`
5. Checks cloud API keys (`GROQ_API_KEY`, `GOOGLE_API_KEY`)
6. Adds cloud models to supported list regardless of GPU
7. Runs determinism self-test (vLLM or cloud APIs)
8. Saves config to `~/.blindference/config.json`

**Env vars used**:
- `BLF_PRIVATE_KEY` — hex private key
- `BLF_KEY_PASSWORD` — keystore password
- `GROQ_API_KEY` — enables Groq backend
- `GOOGLE_API_KEY` — enables Gemini backend

#### `attest`

```bash
blindference-node attest --mock
```

**What it does**:
1. Loads config and wallet
2. Connects to ICL at `BLF_ICL_ENDPOINT`
3. Gets challenge from ICL: `GET /internal/challenge/{address}`
4. Generates mock attestation quote: `HMAC-SHA256(nonce + runtime_hash, mock_key)`
5. Submits attestation: `POST /internal/attestation/verify`
6. Receives `certHash`, `expiry`, `tier` from ICL
7. **Auto-detects on-chain registration**:
   - Checks `NodeRegistry.isActive(address)` + `getNode(address)`
   - If already active → skips tx, prints "Already registered and active"
   - If inactive → warns, suggests `run` to re-activate
   - If not registered → interactive prompt to register with gas estimation
8. Saves updated config with cert hash and expiry

**On-chain registration** (if user confirms):
- Calls `NodeRegistry.register(tier, attestationHash, expiry, models[])`
- Gas estimate shown with 50% buffer
- Transaction sent, receipt waited
- Explorer link printed: `https://sepolia.arbiscan.io/tx/{hash}`

**Env vars used**:
- `BLF_KEY_PASSWORD`
- `BLF_ICL_ENDPOINT`
- `BLF_RPC_URL` (preferred) or `BLF_FHENIX_RPC` (legacy fallback)
- `MOCK_ATTESTATION_KEY`

#### `run`

```bash
blindference-node run --log-level DEBUG
```

**What it does**:
1. Loads config and wallet
2. Checks attestation expiry
3. If expired or missing → auto re-attests via ICL
4. Sets up logging with node address prefix
5. Loads inference backend registry (built-in + custom)
6. Starts 3 concurrent loops:
   - `heartbeat_loop` — ICL + on-chain heartbeats
   - `attestation_watchdog` — auto re-attest before expiry
   - `assignment_poller` — poll ICL for jobs

**Env vars used**: All config fields can be overridden via `BLF_*` prefixed env vars. See Configuration section.

---

## 6. Configuration

### 6.1 Config File (`~/.blindference/config.json`)

```json
{
  "node_address": "0x61e72a02...",
  "keystore_path": "~/.blindference/keystore.json",
  "tier": 0,
  "supported_model_ids": [
    "facebook/opt-125m",
    "groq:llama-3.3-70b-versatile",
    "gemini:gemini-2.5-flash"
  ],
  "custom_backends": [],
  "attestation_backend": "mock",
  "icl_endpoint": "https://icl.blindference.xyz",
  "fhenix_rpc": "",
  "ipfs_gateway": "https://node.lighthouse.storage",
  "model_cache_dir": "~/.blindference/models",
  "log_level": "INFO",
  "zdr_compliant": false,
  "network": "arbitrum_sepolia",
  "attestation_cert_hash": "0x...",
  "attestation_expiry": 1750000000,
  "registered_on_chain": true,
  "stake_amount_wei": 0,
  "cofhe_mode": "bridge",
  "cofhe_endpoint": "",
  "cofhe_chain_id": 421614,
  "skip_output_key_storage": false,
  "payment_service_url": "http://127.0.0.1:8001"
}
```

### 6.2 Environment Variable Overrides

All config fields can be overridden via environment variables prefixed with `BLF_`:

| Env Var | Type | Default | Description |
|---------|------|---------|-------------|
| `BLF_NODE_ADDRESS` | string | `""` | Ethereum address |
| `BLF_KEYSTORE_PATH` | string | `~/.blindference/keystore.json` | Wallet keystore |
| `BLF_TIER` | int | 0 | Attestation tier (0=mock, 1=TPM, 2=TEE) |
| `BLF_SUPPORTED_MODEL_IDS` | list | `[]` | Comma-separated model IDs |
| `BLF_CUSTOM_BACKENDS` | list | `[]` | Comma-separated dotted Python paths |
| `BLF_ATTESTATION_BACKEND` | string | `"mock"` | `mock`, `tpm`, `sgx` |
| `BLF_ICL_ENDPOINT` | string | `"https://icl.blindference.xyz"` | ICL base URL |
| `BLF_RPC_URL` | string | `""` | **Arbitrum Sepolia RPC (preferred)** |
| `BLF_FHENIX_RPC` | string | `""` | Legacy alias for EVM RPC |
| `BLF_IPFS_GATEWAY` | string | `"https://node.lighthouse.storage"` | IPFS download gateway |
| `BLF_MODEL_CACHE_DIR` | string | `~/.blindference/models` | Local model cache |
| `BLF_LOG_LEVEL` | string | `"INFO"` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `BLF_ZDR_COMPLIANT` | bool | `false` | Zero-disclosure requirement |
| `BLF_NETWORK` | string | `"arbitrum_sepolia"` | Network name |
| `BLF_COFHE_MODE` | string | `"bridge"` | `bridge` (TS subprocess) or `python` (HTTP) |
| `BLF_COFHE_ENDPOINT` | string | `""` | Arbitrum Sepolia RPC for CoFHE |
| `BLF_COFHE_CHAIN_ID` | int | 421614 | Chain ID for CoFHE |
| `BLF_SKIP_OUTPUT_KEY_STORAGE` | bool | `false` | Skip on-chain output key storage |
| `BLF_PAYMENT_SERVICE_URL` | string | `"http://127.0.0.1:8001"` | Payment Service base URL for job queries |
| `BLF_KEY_PASSWORD` | string | `""` | Keystore decryption password |
| `GROQ_API_KEY` | string | `""` | Groq API key |
| `GOOGLE_API_KEY` | string | `""` | Google AI API key |
| `MOCK_ATTESTATION_KEY` | string | `"weloveblindference"` | Mock attestation HMAC key |

### 6.3 Tier and Model Mapping

```python
# TIER_SPECS in cli.py
TIER_SPECS = [
    (0, 0.5, ["facebook/opt-125m"]),   # Any GPU with 0.5GB+ VRAM
]

# Cloud models (added regardless of GPU)
_CLOUD_MODELS = {
    "GROQ_API_KEY": ["groq:llama-3.3-70b-versatile"],
    "GOOGLE_API_KEY": ["gemini:gemini-2.5-flash"],
}
```

Nodes with cloud API keys are assigned **tier 0** (widest availability) so they can participate in all quorums.

---

## 7. Job Execution Flow

### 7.1 Assignment to Completion

```python
# assignment_poller in node_loop.py
async def assignment_poller(shutdown, config, icl, w3, wallet, ipfs, cofhe, sem):
    while not shutdown.is_set():
        assignments = await icl.get_assignments()  # GET /internal/assignments/{addr}
        for job in assignments:
            if job_id not in in_flight:
                in_flight.add(job_id)
                task = asyncio.create_task(
                    _job_wrapper(job, config, wallet, w3, icl, ipfs, cofhe, sem)
                )
                task.add_done_callback(lambda t, jid=job_id: in_flight.discard(jid))
        await _sleep_or_shutdown(shutdown, 5)
```

### 7.2 Job Wrapper (Timeout)

```python
async def _job_wrapper(job, config, wallet, w3, icl, ipfs, cofhe, sem):
    role = job.get("role", "leader")
    job_id = job.get("jobId", "?")
    async with sem:  # Max 2 concurrent
        await asyncio.wait_for(
            handle_job(job, config, wallet, w3, icl, ipfs, cofhe),
            timeout=300,  # 5 minutes hard timeout
        )
```

### 7.3 handle_job (job_handler.py)

```python
async def handle_job(assignment, config, wallet, w3, icl, ipfs, cofhe):
    role = assignment.get("role", "leader")
    
    if role == "leader":
        await _do_leader_job(assignment, config, wallet, w3, icl, ipfs, cofhe)
    else:
        await _do_verifier_job(assignment, config, wallet, w3, icl, ipfs, cofhe)
```

### 7.4 Common Steps (Leader + Verifier)

```python
async def _common_steps(assignment, icl, ipfs, cofhe):
    # 1. Claim assignment
    claim_result = await icl.claim_task(job_id, node_address)
    # Returns: { kpHighHandle, kpLowHandle, permit, claimDeadline }
    
    # 2. Decrypt key halves via CoFHE bridge
    #    Uses @cofhe/sdk/node TypeScript subprocess
    high_decrypted = await cofhe.decrypt(kp_high_handle, permit)
    low_decrypted = await cofhe.decrypt(kp_low_handle, permit)
    
    # 3. Reconstruct AES key from two uint128 halves
    aes_key = reconstruct_key(high_decrypted, low_decrypted)
    #    Key format: concatenate high || low → 32 bytes
    
    # 4. Download encrypted blob from IPFS
    encrypted_blob = await ipfs.download(prompt_cid)
    
    # 5. Decrypt blob with AES-256-GCM
    prompt = decrypt_prompt_blob(encrypted_blob, aes_key)
    
    # 6. Run deterministic inference
    result = run_deterministic_inference(model_id, prompt)
    
    # 7. Hash result for commitment
    commitment_hash = compute_commitment(result)
    
    return result, commitment_hash
```

### 7.5 Leader-Specific Steps

```python
async def _do_leader_job(assignment, config, wallet, w3, icl, ipfs, cofhe):
    result, commitment_hash = await _common_steps(assignment, icl, ipfs, cofhe)
    
    # 8. Generate new AES key for output encryption
    output_key = generate_output_key()  # 32 random bytes
    
    # 9. Encrypt output blob
    encrypted_output = encrypt_output_blob(result, output_key)
    
    # 10. Split output key into two uint128 halves for CoFHE
    out_high, out_low = split_key_for_cofhe(output_key)
    
    # 11. CoFHE-encrypt output key halves (via bridge)
    #     The bridge returns CoFPE handles
    
    # 12. Store output key on-chain via PromptKeyStore.storeOutputKey
    #     Only stores if config.skip_output_key_storage is False
    store_output_key(w3, config, wallet, job_id, out_high, out_low, user_address)
    
    # 13. Upload encrypted output to IPFS
    output_cid = await ipfs.upload(encrypted_output)
    
    # 14. Submit to ICL
    await icl.submit_leader_result(
        job_id=job_id,
        output_cid=output_cid,
        commitment_hash=commitment_hash,
        encrypted_output_key_high=str(out_high),
        encrypted_output_key_low=str(out_low),
        output_key_store_tx=tx_hash,
        verdict="CONFIRM",
        confidence=95,
    )
```

### 7.6 Verifier-Specific Steps

```python
async def _do_verifier_job(assignment, config, wallet, w3, icl, ipfs, cofhe):
    result, commitment_hash = await _common_steps(assignment, icl, ipfs, cofhe)
    
    # Verifier only hashes result and submits verdict
    # Does NOT encrypt output or store on-chain
    await icl.submit_verifier_verdict(
        job_id=job_id,
        verifier_address=wallet.address,
        commitment_hash=commitment_hash,
        verdict="CONFIRM",  # or "REJECT" if hash mismatch
        confidence=90,
    )
```

### 7.7 Console Output Format

The node prints structured console output for each job:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  JOB  0x2251ef3ee2da02aa48b…  ROLE: LEADER
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ▸ Claiming assignment
    Job ID                 0x2251ef3ee2da02aa48b3449a46fe2e3526bcc39ab7b8d5033bacfd33d862b86d
    Node address           0x61e72a02...

  ▸ Decrypting prompt key
    kpHighHandle           1234567890...
    kpLowHandle            9876543210...
    Permit imported        true

  ▸ Downloading prompt from IPFS
    CID                    Qm...
    Downloaded             1.2 KB

  ▸ Running inference
    Model                  groq:llama-3.3-70b-versatile
    Provider               groq

  ▸ Submitting result to ICL
    Commitment hash        0xabc123...
    Output CID             Qm...
    Output key store tx    0xdef456...
    Explorer               https://sepolia.arbiscan.io/tx/0xdef456
```

---

## 8. Backend Registry

### 8.1 Built-in Backends

| Backend | Class | Requirements | Model IDs |
|---------|-------|--------------|-----------|
| **vLLM** | `VllmBackend` | NVIDIA GPU + `vllm` package | `facebook/opt-125m` |
| **Groq** | `GroqBackend` | `GROQ_API_KEY` env var | `groq:llama-3.3-70b-versatile` |
| **Gemini** | `GeminiBackend` | `GOOGLE_API_KEY` env var | `gemini:gemini-2.5-flash` |
| **Mock** | `MockBackend` | Always available | `*` (universal fallback) |

### 8.2 Backend Interface

```python
from blindference_node.models.base import ModelBackend

class ModelBackend(ABC):
    @abstractmethod
    def name(self) -> str:
        """Backend identifier, e.g. 'groq', 'gemini', 'vllm'."""
    
    @abstractmethod
    def is_available(self) -> bool:
        """Whether this backend can run (e.g. API key present, GPU available)."""
    
    @abstractmethod
    def supported_models(self) -> list[str]:
        """List of model IDs this backend supports."""
    
    @abstractmethod
    def run(self, model_id: str, prompt: str) -> str:
        """Execute inference and return result string."""
```

### 8.3 Custom Backend Registration

```python
# my_package/backends.py
from blindference_node.models.base import ModelBackend

class MyBackend(ModelBackend):
    def name(self) -> str: return "my-backend"
    def is_available(self) -> bool: return True
    def supported_models(self) -> list[str]: return ["my-model"]
    def run(self, model_id: str, prompt: str) -> str: return "result"
```

```bash
blindference-node models add my_package.backends:MyBackend
```

---

## 9. CoFHE Integration

### 9.1 Bridge Mode (Default)

The node spawns a TypeScript subprocess that loads `@cofhe/sdk/node`:

```python
# crypto.py — CoFHEClient
class CoFHEClient:
    def __init__(self, endpoint: str, chain_id: int, private_key: str):
        # Spawns: node cofhe_bridge.mjs
        # Communicates via JSON-RPC over stdin/stdout
        
    async def decrypt(self, handle: str, permit: str) -> bytes:
        # Sends: { method: "decryptForView", params: [handle, permit] }
        # Receives: { result: "0x..." }
```

**Bridge script**: `blindference_node/scripts/cofhe_bridge.mjs`

### 9.2 Python Mode (Alternative)

Direct HTTP calls to CoFHE endpoints. Lighter weight but requires manual session management.

Set `BLF_COFHE_MODE=python` to use.

### 9.3 Key Operations

```python
# crypto.py

def split_key_for_cofhe(key: bytes) -> tuple[int, int]:
    """Split 32-byte AES key into two uint128 halves."""
    high = int.from_bytes(key[:16], "big")
    low = int.from_bytes(key[16:], "big")
    return high, low

def reconstruct_key(high: int, low: int) -> bytes:
    """Reconstruct 32-byte AES key from two uint128 halves."""
    return high.to_bytes(16, "big") + low.to_bytes(16, "big")

def generate_output_key() -> bytes:
    """Generate random 32-byte AES key."""
    return secrets.token_bytes(32)

def encrypt_output_blob(plaintext: str, key: bytes) -> bytes:
    """Encrypt output with AES-256-GCM."""
    # Returns: nonce (12 bytes) || ciphertext || tag (16 bytes)

def decrypt_prompt_blob(blob: bytes, key: bytes) -> str:
    """Decrypt prompt blob with AES-256-GCM."""
```

---

## 10. On-Chain Contracts

### 10.1 Contract Addresses (Arbitrum Sepolia)

| Contract | Address | ABI File |
|----------|---------|----------|
| **NodeRegistry** (new) | `0x72C0Ead949Fd2C346598a30AF1A69c3c5Cb86082` | `contracts/abis/NodeRegistry.json` |
| **NodeAttestationRegistry** (legacy) | `0xB54e019e9717a8Ed4746bA9d7F1A3F83cf0a35E0` | `contracts/abis/NodeAttestationRegistry.json` |
| **PromptKeyStore** | `0x1E22dD12f448B15f1Ca8560fB6B4463834FaAf73` | `contracts/abis/PromptKeyStore.json` |
| **ExecutionCommitmentRegistry** | `0xcd45aefE9a16772528fa30B7d47958a95e83440C` | `contracts/abis/ExecutionCommitmentRegistry.json` |
| **ResultRegistry** | `0xCebd831eCd00915E299b8Ef2666cAbf942dc7150` | `contracts/abis/ResultRegistry.json` |

### 10.2 Registry.py — On-Chain Wrappers

**File**: `blindference_node/registry.py`

#### `is_node_registered(w3, node_address)`

```python
def is_node_registered(w3, node_address: str) -> tuple[bool, bool]:
    """Check whether a node is registered and active.
    
    Returns:
        (registered, active)
        registered = node has a non-zero operator record
        active = isActive() returns True (attestation + heartbeat valid)
    """
    contract = get_new_node_registry(w3)
    active = contract.functions.isActive(node_address).call()
    node_data = contract.functions.getNode(node_address).call()
    registered = node_data[0] != "0x" + "0" * 40
    return registered, active
```

#### `register_node(w3, config, wallet, ...)`

```python
def register_node(w3, config, wallet, stake_wei=0, cert_hash="", expiry=0) -> str | None:
    """Best-effort registration — tries 3 paths in order:
    1. NodeRegistry.register() (new, preferred)
    2. NodeOperatorRegistry.register() (legacy)
    3. NodeAttestationRegistry.commit() (fallback attestation)
    
    Returns tx hash or None if skipped.
    """
```

#### `update_heartbeat(w3, config, wallet)`

```python
def update_heartbeat(w3, config, wallet):
    """Send on-chain heartbeat. Tries NodeRegistry first, falls back to legacy."""
    new_registry = get_new_node_registry(w3)
    if new_registry:
        tx = new_registry.functions.heartbeat().build_transaction({...})
    else:
        tx = operator_registry.functions.updateHeartbeat().build_transaction({...})
```

#### `store_output_key(w3, config, wallet, job_id, high, low, user)`

```python
def store_output_key(w3, config, wallet, job_id, high_handle, low_handle, user_address):
    """Store output AES key halves on-chain via PromptKeyStore.storeOutputKey().
    
    Calls: storeOutputKey(bytes32 taskId, uint256 KoH, uint256 KoL, address user)
    
    If config.skip_output_key_storage is True, logs and returns dummy result.
    """
```

### 10.3 Gas Estimation

```python
def _estimate_gas_price(w3) -> int:
    """Return current gas price with 50% buffer for Arbitrum Sepolia."""
    base = w3.eth.gas_price
    return int(base * 1.5)
```

Arbitrum Sepolia base fee can spike; the 50% buffer prevents transactions from being stuck.

---

## 11. ICL Client

**File**: `blindference_node/icl_client.py`

### 11.1 REST API Methods

```python
class ICLClient:
    def __init__(self, base_url: str, wallet: LocalAccount):
        self.base_url = base_url
        self.wallet = wallet
    
    async def get_challenge(self) -> dict:
        """GET /internal/challenge/{address}"""
        # Returns: { challengeId, nonce }
    
    async def submit_attestation(self, backend_type, quote, runtime_hash, challenge_id, supported_model_ids) -> dict:
        """POST /internal/attestation/verify"""
        # Returns: { certHash, expiry, tier }
    
    async def send_heartbeat(self) -> dict:
        """POST /internal/heartbeat"""
    
    async def get_assignments(self) -> list[dict]:
        """GET /internal/assignments/{address}"""
        # Returns list of assignment dicts
    
    async def claim_task(self, job_id: str, node_address: str) -> dict:
        """POST /internal/task/claim"""
        # Returns: { kpHighHandle, kpLowHandle, permit, claimDeadline }
    
    async def submit_leader_result(self, job_id, output_cid, commitment_hash, 
                                   enc_out_high, enc_out_low, output_key_store_tx,
                                   verdict, confidence) -> dict:
        """POST /internal/task/result"""
    
    async def submit_verifier_verdict(self, job_id, verifier_address, 
                                      commitment_hash, verdict, confidence) -> dict:
        """POST /internal/task/verify"""
```

### 11.2 Error Handling

- `ICLNodeUnknownError` (401/404): Triggers auto re-attestation in `assignment_poller`
- `asyncio.TimeoutError`: Job exceeds 5-minute timeout → logged error, worker exits
- All other exceptions: Logged as warnings, poller continues

---

## 12. IPFS Client

**File**: `blindference_node/ipfs_client.py`

```python
class IPFSClient:
    def __init__(self, gateway_url: str):
        self.gateway = gateway_url  # e.g. https://node.lighthouse.storage
    
    async def download(self, cid: str) -> bytes:
        """Download blob from IPFS gateway."""
        # GET {gateway}/api/v0/cat?arg={cid}
    
    async def upload(self, data: bytes) -> str:
        """Upload blob to IPFS, return CID."""
        # POST {gateway}/api/v0/add
```

---

## 13. Commitment Scheme

**File**: `blindference_node/commitment.py`

```python
def compute_commitment(result: str) -> str:
    """Compute a deterministic commitment hash of inference result.
    
    Uses keccak256 of the UTF-8 encoded result string.
    This hash is what the leader submits and verifiers compare against.
    """
    return Web3.keccak(text=result).hex()
```

**Determinism requirement**: All nodes must produce byte-identical outputs for the same prompt. This is enforced by:
- Fixed temperature (0.0)
- Fixed seed
- Fixed max_tokens
- No random sampling

If a backend is non-deterministic (e.g., some Gemini models), the verifier may reject the leader's result even if both are "correct."

---

## 14. Determinism Self-Test

```bash
blindference-node test-determinism --model groq:llama-3.3-70b-versatile --prompt "Hello, Blindference"
```

**What it does**:
1. Runs inference twice with the same prompt
2. Compares outputs byte-by-byte
3. If identical → PASSED
4. If different → FAILED (backend is non-deterministic)

This is called automatically during `init`. If it fails, `init` exits with error code 1.

---

## 14.5 Jobs & Earnings Commands (Phase 4)

### `jobs list`

```bash
blindference-node jobs list --limit 20
```

**What it does**:
1. Queries Payment Service `GET /v1/nodes/{address}/jobs?limit=20`
2. Prints rich table with: job_id, role (leader/verifier), status, amount earned
3. Shows totals: total jobs, total BLIND earned

**Example output**:
```
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃              BLINDFERENCE NODE — JOB HISTORY             ┃
┣━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┫
┃  Node Address : 0x61e72a024aE31ed2f0656a37b3B3172CDC364C85 ┃
┃  Total Jobs   : 15                                       ┃
┃  Total Earned : 12.5 BLIND                               ┃
┗━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛

  Job ID          Role      Status     Earned (BLIND)
  ─────────────────────────────────────────────────────
  job_0xabc...    leader    COMPLETED  0.6
  job_0xdef...    verifier  COMPLETED  0.2
```

**Env vars used**:
- `BLF_PAYMENT_SERVICE_URL` — override default Payment Service endpoint

### `jobs claim`

```bash
blindference-node jobs claim
```

**What it does**: No-op. Rewards are automatically distributed by the Payment Service when a job completes successfully. This command exists for CLI completeness and future compatibility.

---

## 15. Auto Re-Attestation

### 15.1 Watchdog Trigger

```python
# attestation_watchdog in node_loop.py
async def attestation_watchdog(shutdown, config, icl, wallet, w3):
    while not shutdown.is_set():
        remaining = config.attestation_expiry - int(time.time())
        if remaining < 6 * 3600:  # Less than 6 hours left
            await _re_attest(icl, config, wallet, w3)
        await _sleep_or_shutdown(shutdown, 600)  # Check every 10min
```

### 15.2 ICL Reset Recovery

```python
# assignment_poller in node_loop.py
async def assignment_poller(...):
    while not shutdown.is_set():
        try:
            assignments = await icl.get_assignments()
        except ICLNodeUnknownError:  # ICL lost node record (DB reset)
            logger.warning("ICL lost node record — auto re-attesting …")
            await _re_attest(icl, config, wallet, w3)
            # Resume polling immediately
        except Exception as exc:
            logger.warning("Assignment poll failed: %s", exc)
```

### 15.3 _re_attest Implementation

```python
async def _re_attest(icl, config, wallet, w3) -> bool:
    backend = MockAttestationBackend()
    challenge = await icl.get_challenge()
    nonce = bytes.fromhex(challenge.get("nonce", "").replace("0x", ""))
    quote = backend.get_quote(nonce)
    result = await icl.submit_attestation(
        backend.backend_type(), quote, backend.get_runtime_hash(),
        challenge.get("challengeId", ""),
        supported_model_ids=config.supported_model_ids,
    )
    config.attestation_cert_hash = result.get("certHash", "")
    config.attestation_expiry = result.get("expiry", 0)
    save_config(config)
    
    # Best-effort on-chain update
    try:
        update_attestation(w3, config, wallet, config.attestation_cert_hash, config.attestation_expiry)
    except Exception as exc:
        logger.warning("On-chain attestation update failed: %s", exc)
    
    return True
```

---

## 16. Wallet Management

**File**: `blindference_node/wallet.py`

```python
def generate_wallet(keystore_path: str) -> str:
    """Generate new Ethereum wallet and save encrypted keystore."""
    account = Account.create()
    keystore = account.encrypt(password="")
    with open(keystore_path, "w") as f:
        json.dump(keystore, f)
    return account.address

def import_wallet(keystore_path: str, private_key: str, password: str = "") -> str:
    """Import private key and save encrypted keystore."""
    account = Account.from_key(private_key)
    keystore = account.encrypt(password)
    with open(keystore_path, "w") as f:
        json.dump(keystore, f)
    return account.address

def load_wallet(keystore_path: str, password: str = "") -> LocalAccount:
    """Load and decrypt keystore."""
    with open(keystore_path) as f:
        keystore = json.load(f)
    private_key = Account.decrypt(keystore, password)
    return Account.from_key(private_key)
```

---

## 17. Project Structure

```
Blindference-node/
├── blindference_node/          # Main package
│   ├── __init__.py             # Version: 0.3.2
│   ├── cli.py                  # CLI entry points (init, attest, run, status, models)
│   ├── node_loop.py            # Daemon: heartbeat, watchdog, poller
│   ├── job_handler.py          # Task execution: claim → decrypt → infer → submit
│   ├── crypto.py               # CoFHE client, AES encryption/decryption, key splitting
│   ├── icl_client.py           # ICL REST API client
│   ├── ipfs_client.py          # IPFS download/upload client
│   ├── wallet.py               # Ethereum wallet generation/loading
│   ├── registry.py             # On-chain contract wrappers (NodeRegistry, PromptKeyStore, etc.)
│   ├── config.py               # Configuration management (Pydantic model + env overrides)
│   ├── execution.py            # Backend registry, inference dispatch, determinism test
│   ├── commitment.py           # Commitment hash computation (keccak256)
│   ├── backend_loader.py       # Dynamic backend loading from dotted paths
│   ├── cloud_inference.py      # Groq/Gemini HTTP API wrappers
│   ├── utils.py                # GPU detection, helpers
│   ├── attestation/
│   │   ├── __init__.py
│   │   └── mock.py             # Mock attestation backend (HMAC-SHA256)
│   ├── models/
│   │   ├── base.py             # ModelBackend abstract base class
│   │   ├── registry.py         # Backend registry (built-in + custom)
│   │   ├── vllm_backend.py     # Local GPU inference via vLLM
│   │   ├── groq_backend.py     # Groq cloud API
│   │   ├── gemini_backend.py   # Google Gemini API
│   │   └── mock_backend.py     # Deterministic SHA-256 fallback
│   ├── contracts/
│   │   └── abis/               # Solidity contract ABIs (JSON)
│   │       ├── NodeRegistry.json
│   │       ├── NodeAttestationRegistry.json
│   │       ├── NodeOperatorRegistry.json
│   │       ├── PromptKeyStore.json
│   │       ├── ExecutionCommitmentRegistry.json
│   │       ├── ResultRegistry.json
│   │       └── PayoutClaimer.json
│   └── scripts/
│       └── cofhe_bridge.mjs    # TypeScript CoFHE bridge subprocess
├── contracts/                  # Duplicate ABIs (for reference)
├── tests/                      # Test suite
│   ├── test_attestation.py
│   ├── test_cofhe_real.py
│   ├── test_commitment.py
│   ├── test_config.py
│   ├── test_crypto.py
│   ├── test_e2e.py
│   ├── test_execution.py
│   ├── test_execution_real.py
│   ├── test_icl_client.py
│   ├── test_ipfs_client.py
│   ├── test_job_handler.py
│   ├── test_node_loop.py
│   ├── test_registry.py
│   └── test_wallet.py
├── pyproject.toml              # Package config, v0.3.2
├── docker-compose.yml          # Docker orchestration
├── Dockerfile                  # Container image
├── README.md                   # Human-facing README (keep concise)
└── AGENTS.md                   # THIS FILE — comprehensive context transfer
```

---

## 18. Testing

```bash
# Run all tests
python -m pytest tests/ -q

# Expected output (as of 2026-05-24):
# 84 passed, 1 skipped, 3 warnings in 6.65s

# Run specific test
pytest tests/test_e2e.py -v
pytest tests/test_job_handler.py -v
pytest tests/test_registry.py -v
```

**Test categories**:
- Unit tests: config, wallet, crypto, commitment, attestation
- Integration tests: ICL client, IPFS client, registry (with mocked Web3)
- E2E tests: Full leader and verifier flows (with mocked ICL server)
- Real tests: `test_cofhe_real.py`, `test_execution_real.py` (require real API keys, skipped by default)

---

## 19. Known Bugs, Workarounds, and Critical Decisions

### 19.1 Groq API 401 "Invalid API Key" — FIXED v0.3.2

**Root cause**: `.env` files with quoted values (`GROQ_API_KEY="gsk_..."`) included literal quotes in the API key.
**Fix**: Both the fallback `.env` parser in `cli.py` and `groq_backend.py._get_api_key()` strip matching quotes.

```python
# cli.py fallback parser
if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
    value = value[1:-1]

# groq_backend.py
class GroqBackend:
    def _get_api_key(self) -> str:
        raw = os.environ.get("GROQ_API_KEY", "").strip()
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ('"', "'"):
            raw = raw[1:-1]
        return raw
```

### 19.2 PyPI Publish Required Trusted Publishing

**Setup**: GitHub Actions `publish.yml` uses `pypa/gh-action-pypi-publish@release/v1` with `permissions: id-token: write`.
**Requirement**: The PyPI project must have a Trusted Publisher configured for:
- Repository: `AbhishekPanwarr/Blindference-node`
- Workflow: `publish.yml`
- Environment: `pypi`

**Trigger**: Push a git tag matching `v*.*.*` (e.g., `git tag v0.3.2 && git push origin v0.3.2`).

### 19.3 NodeRegistry vs Legacy Registries

**New preferred**: `NodeRegistry` at `0x72C0Ead949Fd2C346598a30AF1A69c3c5Cb86082`
- Functions: `register()`, `isActive()`, `getNode()`, `heartbeat()`
- Simpler interface, designed for Blindference

**Legacy fallback**: `NodeAttestationRegistry` at `0xB54e019e9717a8Ed4746bA9d7F1A3F83cf0a35E0`
- Used only if NodeRegistry is not deployed

**Code path**: `registry.py` tries NodeRegistry first, then legacy, then logs warning.

### 19.4 PromptKeyStore Has No `grantDecryptAccess`

**Status**: Deployed contract limitation. `storeKey(allowedNodes=[...])` grants all nodes access atomically.
**Do NOT** try to call `grantDecryptAccess` — it does not exist in the ABI.

### 19.5 CoFHE Decrypt 403

**Root cause**: Browser-generated ctHashes need on-chain ACL creation via `BlindferenceInputVault` (in the main blindference repo).
**Fix**: The main repo's frontend now sends encrypted inputs to `BlindferenceInputVault` before creating sharing permits.
**Node impact**: None — nodes just import permits and call `decryptForView().withPermit()`. The 403 is a frontend/contract issue, not a node issue.

### 19.6 Auto-Detect On-Chain Registration

**Implementation**: `attest` CLI command now checks `is_node_registered()` before prompting to register.
- Already active → "Already registered and active", skips tx
- Inactive → warns, suggests `run` to re-activate
- Not registered → interactive prompt with gas estimate

### 19.7 python-dotenv Dependency

**Added in v0.3.2**: `python-dotenv>=1.0` is now a required dependency. `.env` files in the project directory or `~/.blindference/.env` are automatically loaded on CLI startup.

### 19.8 BLF_RPC_URL Preferred Over BLF_FHENIX_RPC

**Changed in v0.3.2**: The dead Fhenix testnet RPC (`https://testnet.fhenix.zone`) was removed as default. `BLF_RPC_URL` (Arbitrum Sepolia Alchemy) is now the preferred variable.

---

## 20. Docker

```bash
# Build
docker build -t blindference-node .

# Run
docker run -d \
  --name blindference-node \
  -e BLF_KEY_PASSWORD=secure_password \
  -e BLF_RPC_URL=https://arb-sepolia.g.alchemy.com/v2/YOUR_KEY \
  -e GROQ_API_KEY=gsk_YOUR_KEY \
  -v /host/config:/root/.blindference \
  blindference-node run
```

---

## 21. Release History

| Version | Date | Changes |
|---------|------|---------|
| 0.3.2 | 2026-05-24 | Strip .env quotes, fix Groq 401, add python-dotenv, auto-detect on-chain registration, use BLF_RPC_URL |
| 0.3.1 | 2026-05-24 | First PyPI publish attempt (failed auth) |
| 0.3.0 | 2026-05-24 | Restore full CLI, attest, models, registry, crypto, ICL, IPFS, job handler |
| 0.2.x | — | Earlier development versions |
| 0.1.x | — | Initial prototype |

---

## 22. Integration with Blindference Main Repo

This package is the **node runtime** for the Blindference network. The main repo (`github.com/baync180705/blindference`) contains:

- **Frontend**: React/Vite browser client
- **ICL**: FastAPI coordinator that dispatches jobs to nodes
- **Contracts**: Solidity contracts on Arbitrum Sepolia
- **Demo**: Demo vertical contracts (BlindferenceInputVault, etc.)

**Relationship**:
- ICL selects quorum nodes and pushes assignments to node callback URLs
- Nodes run this package to process assignments
- Results are submitted back to ICL for consensus
- ICL commits accepted results on-chain

**Required env vars for integration**:
- `BLF_ICL_ENDPOINT` — must point to the ICL instance
- `BLF_RPC_URL` — Arbitrum Sepolia RPC (same network as ICL)
- `GROQ_API_KEY` or `GOOGLE_API_KEY` — for inference

---

## 23. Troubleshooting

### Node not receiving assignments
1. Check `blindference-node status` — is attestation valid?
2. Check ICL heartbeat logs — are heartbeats succeeding?
3. Check ICL endpoint — is `BLF_ICL_ENDPOINT` correct?
4. Try manual re-attest: `blindference-node attest --mock`

### Groq API 401
1. Check `echo $GROQ_API_KEY` — does it have quotes?
2. Update to v0.3.2+: `pip install -U blindference-node`
3. Re-init: `blindference-node init`

### CoFHE decrypt fails
1. Check `BLF_COFHE_ENDPOINT` — must be Arbitrum Sepolia RPC
2. Check permit format — must be base64-encoded sharing permit
3. Check if job was created after `BlindferenceInputVault` fix (main repo)

### On-chain registration fails
1. Check `BLF_RPC_URL` — must have ETH for gas
2. Check gas price — Arbitrum Sepolia can spike
3. Try legacy registry: modify `registry.py` to force legacy path

---

## 24. License

MIT License — see `LICENSE` file.

---

## 25. Last Updated

This document was last updated on **2026-05-25** for `blindference-node` **v0.3.3**.

**Recent changes**:
- **Jobs & Earnings CLI**: Added `jobs list` and `jobs claim` commands. `jobs list` queries Payment Service for job history and prints rich table.
- **Payment Service URL config**: Added `payment_service_url` to config (default `http://127.0.0.1:8001`), overridable via `BLF_PAYMENT_SERVICE_URL`
- **Directory-local config**: `DEFAULT_CONFIG_DIR` changed from `~/.blindference` to current working directory (`os.getcwd()`)
- **Receipt.status validation**: Added `_require_receipt_success()` to `registry.py`; fixed all 11 transaction functions to verify tx success
- **Node attestation fix**: Replaced stub `update_attestation()` with real `NodeRegistry.updateAttestation()` call; padded cert_hash to 32 bytes
- Strip quotes from `.env` values in fallback parser and Groq API key
- Auto-detect on-chain registration in `attest` CLI
- Add `python-dotenv>=1.0` as required dependency
- Use `BLF_RPC_URL` (Arbitrum Sepolia) over dead Fhenix testnet defaults
- All tests passing (84 passed, 1 skipped)
- Published to PyPI via Trusted Publishing (OIDC)

**Git commits** (as of 2026-05-25):
- `jobs-cli` — feat(node): add jobs list/claim commands and payment_service_url config
- `c866d59` — fix(node): strip quotes from .env values and Groq API key
- `9361d78` — feat: auto-detect on-chain registration + add python-dotenv dep
- `e5687a6` — fix: use BLF_RPC_URL for NodeRegistry checks
