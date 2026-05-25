# Settlement — Reineira Escrow & Automatic Payout

This guide explains how to link a Blindference inference job to a Reineira escrow so that verified outputs automatically trigger USDC payouts to the quorum.

## Overview

The settlement flow bridges three systems:

1. **Reineira** — holds funds in a `ConfidentialEscrow` on Arbitrum Sepolia. The funds release only when the attached `InferenceGate` reports that the condition is met.

2. **Blindference** — runs encrypted inference through a leader + verifiers quorum. When the ICL marks a job as verified, it writes to `ResultRegistry`.

3. **InferenceGate** — a Reineira `IConditionResolver` that reads `ResultRegistry.isConditionMet()`. When the job is verified, the gate opens and the escrow releases cUSDC.

4. **PayoutClaimer** — the escrow beneficiary. After redemption, it distributes 60% to the leader and 20% to each verifier.

## Flow

```
Developer                  Reineira Chain              Blindference ICL
────────                   ─────────────              ────────────────
1. Create escrow
   owner=PayoutClaimer     → EscrowCreated
   resolver=InferenceGate

2. Fund escrow             → EscrowFunded
   (cUSDC deposited)

3. Create Blindference     ───────────────────────────→ stores jobId
   job with escrowId                                     + escrowId

4.                                              ICL selects quorum
                                                Nodes execute inference

5.                                              ICL writes ResultRegistry
                              ← ResultCommitted ── commitResult(taskId, ACCEPTED)

6. PayoutClaimer.claim()    → EscrowRedeemed
   (anyone can call)          cUSDC → leader/verifiers
```

## Prerequisites

- A funded wallet on **Arbitrum Sepolia** with:
  - ETH (for gas)
  - cUSDC (ConfidentialUSDC at `0x42E47f9bA89712C317f60A72C81A610A2b68c48a`)
- The Reineira SDK installed: `npm install @reineira-os/sdk`

## Contract Addresses (Arbitrum Sepolia)

| Contract | Address |
|---|---|
| ConfidentialEscrow | `0xbe1eEB78504B71beEE1b33D3E3D367A2F9a549A6` |
| ConfidentialUSDC (cUSDC) | `0x42E47f9bA89712C317f60A72C81A610A2b68c48a` |
| USDC (mock) | `0x75faf114eafb1BDbe2F0316DF893fd58CE46AA4d` |
| InferenceGate | `0xF3014a79985f83898912cAe2676226310A546905` |
| ResultRegistry | `0xCebd831eCd00915E299b8Ef2666cAbf942dc7150` |
| PayoutClaimer | `0xEfB565c7989dd1dEDD0C5B8c95dA24Ef2d94FBbd` |

## Step-by-Step

### 1. Create the Reineira Escrow

```typescript
import { ReineiraSDK } from '@reineira-os/sdk'

const sdk = ReineiraSDK.create({
  network: 'testnet',
  privateKey: process.env.PRIVATE_KEY,
})
await sdk.initialize()

const INFERENCE_GATE = '0xF3014a79985f83898912cAe2676226310A546905'
const PAYOUT_CLAIMER = '0xEfB565c7989dd1dEDD0C5B8c95dA24Ef2d94FBbd'

// Generate a job ID (or use the one from your Blindference job)
const jobId = '0x' + 'A'.repeat(64) // 32-byte job ID

const vault = await sdk.escrow
  .build()
  .amount(sdk.usdc(100))           // 100 USDC
  .owner(PAYOUT_CLAIMER)           // PayoutClaimer is the beneficiary
  .condition(INFERENCE_GATE, ethers.AbiCoder.defaultAbiCoder().encode(['bytes32'], [jobId]))
  .create()

console.log(`Escrow created: ${vault.id}`)
```

### 2. Fund the Escrow

```typescript
await vault.fund(sdk.usdc(100))
console.log(`Escrow ${vault.id} funded`)
```

### 3. Create the Blindference Job

When submitting your Blindference inference request, include the `escrowId`:

```typescript
// In the Blindference frontend TextInferenceWizard:
// Expand "Advanced / Settlement" and enter the escrow ID.
//
// Or via the API:
const response = await inferenceApi.submitText({
  developer_address: address,
  task_id: taskId,
  mode: 'text',
  text_request: { ... },
  escrow_id: vault.id,  // Link to the Reineira escrow
  ...
})
```

### 4. Wait for Verification

The ICL assigns leader + 2 verifier nodes, they execute inference, and the commitment aggregator evaluates consensus. Once verified, the ICL writes to `ResultRegistry`.

```bash
# Poll for verification status
curl http://icl.blindference.xyz/internal/jobs/{jobId}/status
# → { "status": "VERIFIED", "outputCid": "Qm...", "leaderCommitment": "0x..." }
```

### 5. Redeem the Escrow

After verification, anyone can call `PayoutClaimer.claim()`:

```python
from web3 import Web3
import json

w3 = Web3(Web3.HTTPProvider("https://arb-sepolia.g.alchemy.com/v2/YOUR_KEY"))

with open("contracts/abis/PayoutClaimer.json") as f:
    abi = json.load(f)["abi"]

claimer = w3.eth.contract(
    address="0xEfB565c7989dd1dEDD0C5B8c95dA24Ef2d94FBbd",
    abi=abi,
)

tx = claimer.functions.claim(escrow_id, job_id_bytes).build_transaction({
    "from": wallet.address,
    "nonce": w3.eth.get_transaction_count(wallet.address),
    "gas": 500_000,
})
signed = wallet.sign_transaction(tx)
receipt = w3.eth.wait_for_transaction_receipt(
    w3.eth.send_raw_transaction(signed.raw_transaction)
)
print(f"Escrow redeemed: {receipt.transactionHash.hex()}")
```

### 6. Verify Payout

```python
from web3 import Web3

cUSDC = w3.eth.contract(
    address="0x42E47f9bA89712C317f60A72C81A610A2b68c48a",
    abi=[{"constant":True,"inputs":[{"name":"_owner","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"type":"function"}],
)

leader_balance = cUSDC.functions.balanceOf(leader_address).call()
print(f"Leader cUSDC balance: {leader_balance}")
# Should show ~60 USDC for a 100 USDC escrow
```

## Payout Split

| Role | Percentage |
|---|---|
| Leader | 60% |
| Each Verifier | 20% |

The split is configurable by the PayoutClaimer owner via `setSplit(leaderBps, verifierBps)` where both values are in basis points (e.g., 6000 = 60%).

---

## BLIND Token Rewards (Payment Service)

In addition to Reineira USDC escrows, the **Payment Service** distributes **BLIND token rewards** for every successfully verified inference job:

- **Reward amount**: 1 BLIND per verified job (sourced from Payment Service wallet balance)
- **Split**: 60% leader, 20% each verifier (2 verifiers)
- **Distribution**: Automatic — no manual claiming required
- **Storage**: Per-job reward map stored in `JobRecord.rewards: dict[str, float]`

### Viewing Your Earnings

Use the node CLI to query your earnings history:

```bash
blindference-node jobs list --limit 20
```

This queries `GET /v1/nodes/{address}/jobs` from the Payment Service and displays:
- Total jobs completed
- Total BLIND earned
- Per-job breakdown (role, status, amount)

### Prerequisites for BLIND Rewards

- Node must be registered and active on `NodeRegistry`
- Node must have a valid attestation certificate
- Node must successfully complete its assigned task (leader or verifier)
- Payment Service wallet must be funded with BLIND tokens

## Troubleshooting

| Issue | Solution |
|---|---|
| `Unknown escrow` in InferenceGate | Ensure `onConditionSet` was called with the correct `jobId` during escrow creation |
| `Condition not met` | The job has not been verified yet in ResultRegistry. Check `GET /internal/jobs/{jobId}/status` |
| `Already claimed` | The escrow has already been redeemed. Each escrow can only be claimed once |
| `No payout received` | The escrow may not have been funded, or the `redeem()` call did not transfer cUSDC |
| cUSDC not in wallet | Get testnet cUSDC from the Reineira faucet or by swapping mock USDC |
