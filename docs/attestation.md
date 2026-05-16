# Attestation Guide

## Why Attestation Matters

The Blindference network relies on independent nodes to execute inference. Without attestation, any node could claim to be running the correct software while actually running tampered models that produce wrong (or malicious) outputs.

Attestation provides **cryptographic proof** that a node is running the expected inference engine and hasn't been tampered with. The ICL verifies this proof before the node is eligible for job assignments.

## Attestation Backends

Blindference supports a staged rollout of attestation backends, from zero‑trust developers to hardware‑enforced enterprise nodes.

### Mock Attestation (Current — Phase 1)

**Key**: `weloveblindference` (hardcoded HMAC‑SHA256 key)

**How it works**:
1. The ICL issues a random challenge nonce.
2. The node computes `HMAC‑SHA256(key="weloveblindference", msg=challenge)`.
3. The ICL verifies the HMAC with the same key.

**Trust guarantee**: None. This is purely for pipeline validation and developer testing. Nodes using mock attestation are **capped at tier 0** (low‑value, verifier‑only jobs). The mock backend is explicitly documented as insecure — do not use it for production workloads.

### TPM 2.0 (Next Phase)

**How it will work**:
1. The ICL issues a challenge nonce.
2. The node uses `tpm2-tools` to create a TPM quote binding the challenge nonce to PCR values covering the OS bootchain.
3. The inference engine hash is loaded into PCR 15 by the node daemon at startup.
4. The ICL verifies the quote against the node's endorsement key certificate (pinned at registration).

**Trust guarantee**: OS‑level integrity. The TPM proves the node is running the expected software stack, but does not protect process memory during inference.

**Hardware required**: Any modern PC/server with a TPM 2.0 chip (standard on most machines since 2016).

### AMD SEV‑SNP / Intel TDX (Future)

**How it will work**:
1. The node daemon launches inside an SNP‑protected process or TDX trust domain.
2. The AES prompt key from CoFHE is only materialized within the enclave's encrypted memory — never touching the host OS.
3. `sev-guest-util` (AMD) or `tdx-attest` (Intel) generates an attestation quote signed by the manufacturer's key distribution service.
4. The ICL verifies against AMD's or Intel's certificate chain.

**Trust guarantee**: Hardware‑enforced memory encryption. Even the machine owner cannot read process memory. This closes the execution‑layer trust gap entirely.

**Hardware required**: AMD EPYC with SEV‑SNP enabled in BIOS, or Intel Xeon with TDX enabled in BIOS.

## Attestation Flow (Step‑by‑Step)

The attestation process is identical across all backends:

```
   ICL                           Node
   ───                           ────
1. Generate challenge nonce
   ───── GET /challenge ────────→
                              2. Receive nonce
                              3. attestation_backend.get_quote(nonce)
   ←───── POST /verify ──────── 4. Submit {backendType, quote, runtimeHash}
5. Verify quote against root of trust
6. Post cert to NodeAttestationRegistry (on‑chain)
   ←───── 200 {certHash, expiry, tier} ─
```

### Certificate Lifecycle

- Certificates are valid for **48 hours** from issuance.
- The **attestation watchdog** (running as part of `blindference-node run`) checks every 10 minutes. If the certificate expires within the next **6 hours**, it automatically re‑attests.
- Manual re‑attestation: `blindference-node attest` at any time.
- Expired certificates: the node becomes ineligible for new job assignments until re‑attested.

## Re‑Attestation

### Automatic

The daemon handles re‑attestation without operator intervention. Logs:

```
[2026-05-17T06:00:00] [INFO   ] [0xf39Fd6e5] Cert expires in 18000s — re‑attesting …
[2026-05-17T06:00:01] [INFO   ] [0xf39Fd6e5] Attestation renewed — new expiry: 1747519201
```

### Manual

```bash
blindference-node attest
```

Useful after hardware changes, OS updates, or switching attestation backends.

## Troubleshooting

| Issue | Resolution |
|---|---|
| `Re‑attestation failed: ICL connection error` | Check network; ensure ICL endpoint is accessible. |
| `Attestation certificate expired` | Run `blindference-node attest` immediately. |
| Certificate expiring every 48 h (normal) | The watchdog handles it; no manual action needed. |
| Mock attestation always tier 0 | Expected — mock nodes cannot serve tier 1+ jobs. |
