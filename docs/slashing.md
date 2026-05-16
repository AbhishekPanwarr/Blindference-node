# Slashing & Recovery

## Why Slashing Exists

Blindference nodes **stake collateral** when they register on‑chain. This stake provides economic security — if a node produces a wrong inference output, fails to maintain its attestation, or violates the protocol rules, a portion of its stake is forfeited (slashed). The slashed funds compensate the affected user and incentivize honest behavior.

Slashing parameters are defined in the protocol contracts but are **not yet enforced on testnet**. This document describes the rules as they will function in production.

## Slash Conditions

### 1. Output Mismatch (Wrong Inference)

| Parameter | Value |
|---|---|
| **Trigger** | The leader's output commitment differs from the 2/3 quorum majority. |
| **Slash amount** | 10% of staked amount |
| **Beneficiary** | Slashed funds go to the insurance pool; user compensated from insurance. |
| **Fault determination** | The ICL compares three commitments: leader, verifier 1, verifier 2. The outlier is slashed. |

### 2. Catastrophic Quorum Failure

| Parameter | Value |
|---|---|
| **Trigger** | All three nodes post different commitments — no 2/3 consensus. |
| **Slash amount** | 10% of stake for **all three** nodes. |
| **Beneficiary** | User receives full refund from the insurance pool. Slashed funds replenish the pool. |

### 3. Expired Attestation

| Parameter | Value |
|---|---|
| **Trigger** | A node serves a job while its attestation certificate has expired. |
| **Slash amount** | 5% of staked amount |
| **Recovery** | Re‑attest immediately. The remaining stake is unlocked after the dispute window passes. |

### 4. Early Stake Withdrawal During Open Dispute

| Parameter | Value |
|---|---|
| **Trigger** | A node initiates withdrawal while an active dispute exists against it. |
| **Slash amount** | The disputed portion of the stake is forfeited entirely. |
| **Recovery** | The undisputed portion is withdrawable after the 96 h unbonding period. |

## Unbonding Schedule

| Phase | Duration | Description |
|---|---|---|
| **Job cooling** | 96 h after last job completion | No withdrawal until all recent jobs are finalized. |
| **Dispute window** | 72 h | Any party can file a dispute during this period. |
| **Total unbonding** | 168 h (7 days) | Full withdrawal available after both periods. |

During the unbonding period, the node remains registered but ineligible for new jobs.

## Recovery After a Slash

### Step 1 — Diagnose

Check logs in `~/.blindference/logs/` (coming in a future phase) and the output of `blindference-node status` to determine the slash reason.

### Step 2 — Fix the Root Cause

| Cause | Fix |
|---|---|
| Output mismatch | Verify your GPU drivers and model weights. Run `blindference-node init` determinism self‑test again. |
| Expired attestation | Run `blindference-node attest` immediately. |
| Hardware failure | Replace faulty hardware before re‑registering. |

### Step 3 — Re‑Register

```bash
blindference-node init
```

This generates a fresh attestation certificate and attempts on‑chain re‑registration with the remaining stake. You may need to **top up your stake** if the slashed amount brought it below the minimum tier requirement.

### Step 4 — Rebuild Reputation

After a slash, your node's reputation score drops. To recover:

- Consistently produce correct outputs — each accepted job increments reputation.
- Avoid multiple slashes in a short period — consecutive slashes may trigger deactivation.
- Keep attestation current — expired‑cert slashes are easily avoidable.

## Node Deactivation

If a node is **inactive** (no heartbeat) for more than 120 seconds, it is temporarily excluded from job assignment. Prolonged inactivity (7+ days) may result in forced unbonding and stake return minus a penalty.

Re‑activation is automatic: simply restart the daemon with `blindference-node run`. No re‑registration is needed unless the certificate has expired.

## Testnet Caveat

Slashing is **not enforced** on the current Fhenix testnet deployment. During testnet:

- Nodes can register without actual stake.
- Wrong outputs do not result in real fund loss.
- The slashing infrastructure (challenge/vote/execute) is defined in the contracts but bypassed for testnet.

This will change when the protocol moves to mainnet. Operators should treat testnet as a dry‑run — **behave as if slashing were active** to develop good habits.
