# Hardware Requirements

## GPU Tiers

Blindference assigns each node a tier based on available VRAM. The tier determines which models the node can serve and the job value it is eligible for.

| Tier | VRAM | Supported Models | Recommended GPU |
|---|---|---|---|
| 0 (Standard) | 512 MB – 27 GB | `qwen2.5-7b` | NVIDIA RTX 4090, A10, RTX 3080 |
| 1 (Pro) | 28 GB – 64 GB | `qwen2.5-7b`, `qwen2.5-14b`, `qwq-32b` | NVIDIA A100 40GB |
| 2 (Enterprise) | ≥ 65 GB | all three + `llama3.1-70b` | NVIDIA H100 80GB, A100 80GB |

### VRAM per Model

| Model | VRAM Required | Tier |
|---|---|---|
| OPT-125M | ~500 MB | 0 (test only) |
| Qwen2.5-7B-Instruct | ~14 GB | 0+ |
| Qwen2.5-14B-Instruct | ~28 GB | 1+ |
| QwQ-32B-Preview | ~65 GB | 2+ |
| Llama-3.1-70B-Instruct | ~80 GB | 2 |

Multi‑GPU configurations are not supported in v1. Models use a single GPU.

For determinism self‑testing without full model VRAM requirements, use `facebook/opt-125m` (~500 MB). This is the minimum viable model for confirming byte‑identical outputs. It is not used for production inference — only for the `test-determinism` command.

## TEE-Capable CPUs

For advanced attestation backends (Phase 2+ of the attestation rollout), the following hardware is required:

| Backend | Required Hardware | Trust Guarantee |
|---|---|---|
| **Mock** | Any machine | None — developer use only |
| **TPM 2.0** | TPM 2.0 chip (standard on most PCs since 2016) | OS‑level integrity |
| **AMD SEV‑SNP** | AMD EPYC with SEV‑SNP enabled in BIOS | Hardware‑enforced memory encryption |
| **Intel TDX** | Intel Xeon with TDX enabled in BIOS | Hardware‑enforced memory encryption |

For TPM: run `tpm2_getcap pcrs` to verify your chip is available.
For SEV‑SNP: verify with `dmesg | grep SEV` and ensure `mem_encrypt=on` and `kvm_amd.sev_snp=1` are set in kernel parameters.

## Disk Space

Plan for **2× the largest model** you intend to serve. Models are cached in `~/.blindference/models/`.

| Recommendation | Amount |
|---|---|
| Minimum free disk | 50 GB |
| Tier 0 (7B model) | 30 GB |
| Tier 1 (32B model) | 130 GB |
| Tier 2 (70B model) | 180 GB |

Models are downloaded on‑demand when a job is assigned. The LRU cache evicts the least recently used model when disk space is low.

## Network

All communication is **outbound HTTPS**. No inbound ports need to be opened (the node uses a polling model).

| Endpoint | Purpose |
|---|---|
| ICL (`https://icl.blindference.xyz`) | Job assignment, attestation, result submission |
| Fhenix RPC (`https://testnet.fhenix.zone`) | On‑chain contract calls |
| IPFS Gateway (`https://node.lighthouse.storage`) | Blob upload / download |
| Model Registry | Model weight downloads (coming in a future phase) |

Bandwidth: model downloads can reach up to 140 GB for the largest models. A 100 Mbps connection is recommended for tier 2 nodes.

## Operating System

Linux is recommended. The package has been tested on Ubuntu 22.04+ and Debian 12+. Windows support is limited (signal handling, nvidia‑smi parsing), but the package installs and runs on any platform.

## Docker

A `Dockerfile` and `docker-compose.yml` are provided in the repository. The Docker image requires the **NVIDIA Container Toolkit** (`nvidia-docker2`) for GPU access inside containers.
