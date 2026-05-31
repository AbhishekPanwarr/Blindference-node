```mermaid
%%{init: {'theme': 'dark', 'themeVariables': { 'primaryColor': '#f97316', 'primaryTextColor': '#ffffff', 'primaryBorderColor': '#c2410c', 'lineColor': '#a855f7', 'secondaryColor': '#22d3ee', 'tertiaryColor': '#0f0f1a'}}}%%
flowchart TB
    subgraph User["👤 User / Frontend"]
        direction TB
        MM[MetaMask Wallet]
        APP[Blindference App]
    end

    subgraph ICL["🔷 Inference Coordination Layer"]
        direction TB
        API[REST API<br/>icl.blindference.xyz]
        QS[Quorum Selector]
        DIS[Task Dispatcher]
    end

    subgraph Node["🟠 Blindference Node<br/>CENTERPIECE"]
        direction TB
        HB["💓 Heartbeat<br/>POST /internal/heartbeat<br/>Every 60s"]
        POLL["📡 Assignment Poller<br/>GET /internal/assignments<br/>Every 5s"]
        COFHE["🔐 CoFHE Bridge<br/>decryptForView()<br/>Node.js subprocess"]
        INF["🤖 Inference Worker<br/>Groq / Gemini / vLLM"]
        UP["📤 IPFS Uploader<br/>pinFileToIPFS"]
        
        HB --> POLL
        POLL --> COFHE
        COFHE --> INF
        INF --> UP
    end

    subgraph External["☁️ External Services"]
        direction TB
        CF[CoFHE Network<br/>Threshold FHE Decryption]
        IP[IPFS Gateway<br/>Pinata / ipfs.io]
        LLM[LLM Provider<br/>Groq / Gemini / Local]
        CH[Arbitrum Sepolia<br/>On-Chain Registry]
    end

    subgraph Quorum["✅ Quorum Consensus"]
        direction LR
        L["👑 Leader<br/>60% Reward"]
        V1["🔍 Verifier 1<br/>20% Reward"]
        V2["🔍 Verifier 2<br/>20% Reward"]
    end

    subgraph Dashboard["📊 Dashboard"]
        DB[www.blindference.xyz<br/>Earnings & Status]
    end

    User -->|"1. Submit encrypted<br/>inference request"| ICL
    ICL -->|"2. Select quorum<br/>(1 Leader + 2 Verifiers)"| Node
    Node -->|"3a. Heartbeat"| ICL
    Node -->|"3b. Decrypt prompt<br/>ACL-protected handles"| CF
    Node -->|"3c. Download blob"| IP
    Node -->|"3d. Run inference"| LLM
    Node -->|"3e. Upload result<br/>encrypted output"| IP
    Node -->|"3f. Commit hash<br/>on-chain heartbeat"| CH
    Node -->|"4. Submit result"| Quorum
    Quorum -->|"5. Compare & consensus"| ICL
    ICL -->|"6. Payout rewards"| CH
    CH -->|"7. View earnings"| Dashboard

    style Node fill:#1a1a2e,stroke:#f97316,stroke-width:4px,color:#fff
    style User fill:#0f0f1a,stroke:#22d3ee,stroke-width:2px,color:#fff
    style ICL fill:#0f0f1a,stroke:#a855f7,stroke-width:2px,color:#fff
    style External fill:#0f0f1a,stroke:#22d3ee,stroke-width:2px,color:#fff
    style Quorum fill:#0f0f1a,stroke:#22d3ee,stroke-width:2px,color:#fff
    style Dashboard fill:#0f0f1a,stroke:#f97316,stroke-width:2px,color:#fff
    style HB fill:#16213e,stroke:#f97316,stroke-width:1px,color:#fff
    style POLL fill:#16213e,stroke:#f97316,stroke-width:1px,color:#fff
    style COFHE fill:#16213e,stroke:#f97316,stroke-width:1px,color:#fff
    style INF fill:#16213e,stroke:#f97316,stroke-width:1px,color:#fff
    style UP fill:#16213e,stroke:#f97316,stroke-width:1px,color:#fff
```

## Blindference Node Architecture

**Data Flow:**
1. **User** submits encrypted prompt via MetaMask + Blindference App
2. **ICL** (icl.blindference.xyz) selects quorum: 1 Leader + 2 Verifiers
3. **Node** receives assignment, runs 5 concurrent processes:
   - **Heartbeat** (60s): Proves liveness to ICL
   - **Poller** (5s): Checks for new inference jobs
   - **CoFHE Bridge**: Decrypts prompt via threshold FHE (ACL-protected)
   - **Inference Worker**: Runs LLM (Groq/Gemini/vLLM)
   - **IPFS Uploader**: Uploads encrypted result to IPFS
4. **Quorum**: All 3 nodes submit result hashes. Leader output used if 2+ verifiers confirm.
5. **On-Chain**: Commitments recorded, rewards auto-distributed (60% leader, 20% each verifier)
6. **Dashboard**: View real-time earnings at [www.blindference.xyz](https://www.blindference.xyz)

**API Calls Labeled:**
- `POST /internal/heartbeat` — ICL liveness proof (free, every 60s)
- `GET /internal/assignments/{addr}` — Fetch pending jobs (every 5s)
- `decryptForView()` — CoFHE threshold decryption (with sharing permit)
- `pinFileToIPFS` — Upload encrypted output to IPFS via Pinata
- `NodeRegistry.heartbeat()` — On-chain liveness (gas tx, every 10 days)

**Colors:**
- 🟠 Orange (`#f97316`) — Node processes (the hero element)
- 🔵 Cyan (`#22d3ee`) — User, external services, consensus, dashboard
- 🟣 Purple (`#a855f7`) — ICL coordination layer
- ⚫ Dark (`#0f0f1a`) — Background (matches dashboard dark theme)
