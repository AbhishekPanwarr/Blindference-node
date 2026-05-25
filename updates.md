# Blindference Node Updates

This document tracks major releases and architectural changes to the Blindference Node runtime.

## Latest Release — Version 0.3.3 (Phase 4-5)

### Phase 5 — Jobs & Earnings CLI

#### 1. `jobs list` Command

Query Payment Service for completed jobs and earnings:

```bash
blindference-node jobs list --limit 20
```

- Fetches from `GET /v1/nodes/{address}/jobs?limit=20`
- Prints rich table: job_id, role, status, amount_earned
- Shows totals: total jobs, total BLIND earned

#### 2. `jobs claim` Command

No-op placeholder. Rewards are automatically distributed by the Payment Service on job completion. Exists for CLI completeness.

#### 3. Payment Service Integration

- `config.py`: Added `payment_service_url: str = "http://127.0.0.1:8001"`
- Env override: `BLF_PAYMENT_SERVICE_URL`
- Node runtime can query its own earnings history from the Payment Service

#### 4. Hardening Fixes

- **Receipt validation**: `_require_receipt_success()` ensures all 11 on-chain transaction functions verify `receipt.status == 1`
- **Attestation fix**: Real `NodeRegistry.updateAttestation()` call with 32-byte cert_hash padding
- **Directory-local config**: Default config directory changed from `~/.blindference` to `os.getcwd()` for project-local isolation

### Previous Major Changes

#### 1. Auto-Re-Attestation (New)

Nodes now self-heal without manual intervention:

- **Startup check**: On `blindference-node run`, the daemon checks if the attestation certificate is missing or expired
- **Auto-re-attest**: Automatically generates a new mock attestation quote, submits to ICL challenge/verify endpoint, and persists the new certificate
- **Watchdog**: Background task checks every 10 minutes. If certificate expires within 6 hours, triggers re-attestation proactively
- **No manual `attest` command needed**: The `attest` CLI command is now a stub — auto-re-attest handles all cases

This eliminates the operational burden of manually re-attesting nodes after ICL restarts or certificate expiry.

#### 2. CoFHE Bridge Mode (Default)

Changed default CoFHE client from direct HTTP (`python` mode) to TypeScript subprocess (`bridge` mode):

- **Bridge mode**: Spawns `@cofhe/sdk/node` subprocess for CoFHE operations. More reliable SDK lifecycle, proper WASM loading, better error handling
- **Python mode**: Direct HTTP to CoFHE endpoints. Still available as fallback via `BLF_COFHE_MODE=python`
- **Mock mode removed**: `MockCoFHEClient` class deleted entirely. All code paths now use real CoFHE encryption/decryption

This ensures nodes always use production-grade CoFHE operations, never falling back to insecure mock paths.

#### 3. Job Handler Hardening

The job execution pipeline now validates critical preconditions:

- **Missing key handles abort**: If `claim_task` fails or returns no `kpHighHandle`/`kpLowHandle`, the job aborts immediately instead of falling back to a mock key
- **Explicit error logging**: Each failure path logs the exact reason (claim failed, missing handles, IPFS error, CoFHE error, inference error)
- **Concurrent job limit**: Default semaphore of 2 concurrent jobs prevents resource exhaustion

This prevents silent failures where nodes would produce incorrect results using fallback keys.

#### 4. Test Suite Expansion

Comprehensive test coverage added:

- **Crypto tests** (19 tests): AES blob encryption/decryption, CoFHE handle parsing, key splitting
- **Job handler tests** (9 tests): Leader flow, verifier flow, claim failure, ICL claim failure, zero-address handling, verdict matching
- **Node loop tests**: Heartbeat, watchdog, assignment polling
- **ICL client tests**: Challenge, attestation, assignments, task claim/result/verify
- **E2E tests**: Full leader and verifier flows with mock ICL server

All tests pass: `pytest tests/ -v` — 84 passed, 1 skipped

#### 5. Configuration Improvements

- **Config path override**: `BLF_CONFIG_PATH` env var for non-default config locations
- **Password from env**: `BLF_KEY_PASSWORD` for non-interactive daemon startup
- **Model selection**: `BLF_SUPPORTED_MODEL_IDS` as comma-separated list
- **Chain-agnostic**: `BLF_COFHE_CHAIN_ID` for multi-chain support

### Technical Decisions

- **Auto-re-attest as default**: No CLI flag needed because attestation expiry is a universal concern
- **Bridge mode as default**: TypeScript subprocess handles SDK edge cases (WASM loading, session lifecycle) better than raw HTTP
- **Abort on missing handles**: Security-first — better to fail a job than produce a potentially incorrect result with a mock key
- `HEARTBEAT_GRACE_SECONDS: 300` (5 min): Balances ICL restart resilience vs stale-node detection
- `attestation_expiry == 0` triggers auto-re-attest: Handles fresh installations without requiring manual `attest` command

### Bug Fixes

- **Claim task hex parsing**: `claim_task` endpoint now correctly parses `0x`-prefixed hex handles with `int(val, 16)` instead of `int(val)`
- **Assignment field mapping**: `kpHighHandle`/`kpLowHandle` properly extracted from ICL assignment responses
- **IPFS timeout**: Added configurable timeout for blob downloads to prevent hung workers
- **CoFHE session refresh**: Bridge subprocess auto-refreshes CoFHE session before long-running operations

### Known Limitations

- `blindference-node attest` command is a stub — use auto-re-attest via `blindference-node run`
- `blindference-node status` command is a stub — check logs for node state
- `blindference-node withdraw` command is a stub — stake withdrawal not yet implemented
- Web-based node dashboard not yet implemented
- GPU determinism test requires vLLM and NVIDIA GPU

---

## Previous Releases

### Version 0.2.0 — Text Inference Support

- Added AES-256-GCM blob encryption/decryption for text prompts
- Added IPFS blob download/upload for encrypted prompts and outputs
- Added `PromptKeyStore` integration for CoFHE-encrypted key halves
- Added Groq Llama 3 and Google Gemini API inference
- Added output key splitting, encryption, and on-chain storage

### Version 0.1.0 — Risk Scoring Foundation

- Initial node runtime with risk scoring pipeline
- CoFHE feature decryption via imported sharing permits
- Event-driven task dispatch from ICL
- Leader/verifier role separation
- Result hash computation and submission
- On-chain heartbeat and attestation

### Infrastructure Foundation

- CLI with `init`, `run`, `attest` commands
- Encrypted keystore generation
- Mock attestation (tier 0)
- ICL REST client
- Configuration management with env overrides
- Docker containerization
- pytest test framework
