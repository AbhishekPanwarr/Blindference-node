# Blindference Node Architecture — ASCII Fallback

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BLINDFERENCE NODE ARCHITECTURE                        │
│              Decentralized Confidential AI Execution on Arbitrum Sepolia       │
└─────────────────────────────────────────────────────────────────────────────┘

    ┌──────────────┐         ┌──────────────────┐         ┌──────────────┐
    │   👤 USER    │         │  🔷 ICL COORD     │         │ ☁️ EXTERNAL  │
    │  / FRONTEND  │         │   INATOR         │         │  SERVICES   │
    │              │         │                  │         │              │
    │ • MetaMask   │──1─────→│ • Receive request │──2─────→│ • CoFHE      │
    │ • Blindference│ Submit  │ • Select quorum   │ Dispatch│   Network    │
    │   App        │encrypted│ • Dispatch task   │to node │ • IPFS       │
    │ • Encrypted  │prompt   │ • icl.blindference│        │   Gateway    │
    │   prompt     │        │   .xyz            │        │ • LLM        │
    │ • CoFHE      │        │                  │        │   Provider   │
    │   permit     │        │                  │        │ • Arbitrum   │
    └──────────────┘        └──────────────────┘        │   Sepolia    │
                                   │                      └──────────────┘
                                   │                              ↑
                                   ↓ 2. Dispatch                  │ 3b. Decrypt
                        ┌──────────────────────┐                 │
                        │  🟠 BLINDFERENCE NODE │←───────────────┘
                        │     CENTERPIECE      │←────────────────┐
                        │                      │                 │
                        │  ┌────────────────┐  │                 │
                        │  │ 💓 Heartbeat   │  │                 │
                        │  │ POST /internal │  │                 │
                        │  │ /heartbeat     │  │                 │
                        │  │ Every 60s      │  │                 │
                        │  └────────────────┘  │                 │
                        │                      │                 │
                        │  ┌────────────────┐  │                 │
                        │  │ 📡 Assignment  │  │                 │
                        │  │ Poller         │  │                 │
                        │  │ GET /internal/ │  │                 │
                        │  │ assignments    │  │                 │
                        │  │ Every 5s       │  │                 │
                        │  └────────────────┘  │                 │
                        │                      │                 │
                        │  ┌────────────────┐  │                 │
                        │  │ 🔐 CoFHE Bridge │  │                 │
                        │  │ decryptForView │──┼──────3b. Decrypt─┘
                        │  │ Node.js proc   │  │   (threshold FHE)
                        │  └────────────────┘  │
                        │                      │
                        │  ┌────────────────┐  │
                        │  │ 🤖 Inference   │  │
                        │  │ Worker         │  │
                        │  │ Groq / Gemini  │──┼──────3d. Inference
                        │  │ / vLLM         │  │
                        │  └────────────────┘  │
                        │                      │
                        │  ┌────────────────┐  │
                        │  │ 📤 IPFS        │──┼──────3e. Upload
                        │  │ Uploader       │  │   encrypted output
                        │  │ pinFileToIPFS  │  │
                        │  └────────────────┘  │
                        │                      │
                        └──────────────────────┘
                                   │
                                   │ 4. Submit hash
                                   ↓
                        ┌──────────────────────┐
                        │   ✅ QUORUM CONSENSUS │
                        │                      │
                        │   ┌────────┐ ┌────┐ ┌────┐
                        │   │ 👑     │ │ 🔍 │ │ 🔍 │
                        │   │ Leader │ │ V1 │ │ V2 │
                        │   │  60%   │ │20% │ │20% │
                        │   └────────┘ └────┘ └────┘
                        │                      │
                        │   2+ verifiers must   │
                        │   confirm leader     │
                        │   output hash        │
                        └──────────────────────┘
                                   │
                                   │ 5. Consensus
                                   ↓
                        ┌──────────────────────┐
                        │    ⛓ ARBITRUM        │
                        │    SEPOLIA            │
                        │                      │
                        │ • Record commitment  │
                        │ • Auto-distribute    │
                        │   rewards            │
                        │ • Staking / slashing │
                        └──────────────────────┘
                                   │
                                   │ 6. Rewards
                                   ↓
                        ┌──────────────────────┐
                        │   📊 DASHBOARD       │
                        │                      │
                        │ www.blindference.xyz │
                        │                      │
                        │ • Total jobs         │
                        │ • Success rate       │
                        │ • BLIND earned       │
                        │ • Current stake      │
                        │ • Job history        │
                        └──────────────────────┘

LEGEND:
═══════
🟠  Orange  = Node processes (hero element)
🔵  Cyan    = External services & user
🟣  Purple  = ICL coordination layer
⚫  Dark    = Background (matches dashboard)

API CALLS:
══════════
1. POST /v1/inference/request       — User submits encrypted prompt
2. GET /internal/assignments/{addr} — Node fetches pending jobs
3. POST /internal/heartbeat         — Node proves liveness (60s)
4. decryptForView()                  — CoFHE threshold decryption
5. pinFileToIPFS                     — Upload encrypted result to IPFS
6. NodeRegistry.heartbeat()          — On-chain liveness (10 days)

DATA FLOW:
══════════
User → ICL → Node → CoFHE (decrypt) → IPFS (download prompt) 
  → LLM (inference) → IPFS (upload result) → Quorum → On-Chain → Dashboard
```
