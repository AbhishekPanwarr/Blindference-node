import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

installLocalStorageShim()

const [{ createCofheClient, createCofheConfig }, { Encryptable, FheTypes }, { chains }, { PermitUtils }, { createPublicClient, createWalletClient, http }] = await Promise.all([
  import('@cofhe/sdk/node'),
  import('@cofhe/sdk'),
  import('@cofhe/sdk/chains'),
  import('@cofhe/sdk/permits'),
  import('viem'),
  import('viem/accounts'),
])

function installLocalStorageShim() {
  if (globalThis.localStorage && typeof globalThis.localStorage.setItem === 'function') {
    return
  }

  const storageDir = path.join(process.env.HOME || os.homedir() || '.', '.blindference-cofhe')
  const storageFile = path.join(storageDir, 'localstorage.json')

  const readStore = () => {
    try {
      if (!fs.existsSync(storageFile)) return {}
      return JSON.parse(fs.readFileSync(storageFile, 'utf8'))
    } catch {
      return {}
    }
  }

  const writeStore = (data) => {
    fs.mkdirSync(storageDir, { recursive: true })
    fs.writeFileSync(storageFile, JSON.stringify(data))
  }

  globalThis.localStorage = {
    getItem(key) {
      const store = readStore()
      return key in store ? String(store[key]) : null
    },
    setItem(key, value) {
      const store = readStore()
      store[key] = String(value)
      writeStore(store)
    },
    removeItem(key) {
      const store = readStore()
      delete store[key]
      writeStore(store)
    },
    clear() {
      writeStore({})
    },
    key(index) {
      const keys = Object.keys(readStore())
      return keys[index] || null
    },
    get length() {
      return Object.keys(readStore()).length
    },
  }
}

async function createClient(payload) {
  const privateKey = payload.privateKey || process.env.BLF_PRIVATE_KEY
  const rpcUrl = payload.rpcUrl

  if (!privateKey) {
    throw new Error('Missing privateKey in payload or BLF_PRIVATE_KEY env var')
  }
  if (!rpcUrl) {
    throw new Error('Missing rpcUrl in payload')
  }

  const { privateKeyToAccount } = await import('viem/accounts')
  const { arbitrumSepolia } = await import('viem/chains')
  const { createPublicClient, createWalletClient, http } = await import('viem')

  const account = privateKeyToAccount(privateKey)

  const publicClient = createPublicClient({
    chain: arbitrumSepolia,
    transport: http(rpcUrl),
  })
  const walletClient = createWalletClient({
    account,
    chain: arbitrumSepolia,
    transport: http(rpcUrl),
  })

  const config = createCofheConfig({
    supportedChains: [chains.arbSepolia],
    fheKeyStorage: null,
  })
  const client = createCofheClient(config)
  await client.connect(publicClient, walletClient)

  return { client, publicClient, walletClient, account }
}

async function parseJsonInput() {
  return new Promise((resolve, reject) => {
    let data = ''
    process.stdin.setEncoding('utf8')
    process.stdin.on('data', (chunk) => { data += chunk })
    process.stdin.on('end', () => {
      try {
        resolve(JSON.parse(data))
      } catch (err) {
        reject(new Error('Invalid JSON stdin: ' + (err instanceof Error ? err.message : String(err))))
      }
    })
    process.stdin.on('error', (err) => reject(err))
  })
}

async function decryptPromptKey(payload) {
  const { client, account } = await createClient(payload)
  const permit = await client.permits.getOrCreateSelfPermit(undefined, account.address, {
    issuer: account.address,
    name: payload.permitName || 'Blindference Prompt Key Permit',
  })

  const high = await client
    .decryptForView(BigInt(payload.highHandle), FheTypes.Uint128)
    .withPermit(permit)
    .execute()
  const low = await client
    .decryptForView(BigInt(payload.lowHandle), FheTypes.Uint128)
    .withPermit(permit)
    .execute()

  return {
    high: high.toString(),
    low: low.toString(),
    permitHash: permit.hash,
  }
}

async function encryptUint128(payload) {
  const { client } = await createClient(payload)
  const values = Array.isArray(payload.values) ? payload.values : []
  const encrypted = await client
    .encryptInputs(values.map((value) => Encryptable.uint128(BigInt(value))))
    .execute()

  return {
    results: encrypted.map((item) => ({
      ctHash: item.ctHash.toString(),
      securityZone: item.securityZone,
      utype: Number(item.utype),
      signature: item.signature,
    })),
  }
}

async function storePromptKey(payload) {
  const { publicClient, walletClient } = await createClient(payload)

  const promptKeyStoreAbi = [
    {
      type: 'function',
      name: 'storeKey',
      inputs: [
        { name: 'jobId', type: 'bytes32', internalType: 'bytes32' },
        {
          name: 'encHigh',
          type: 'tuple',
          internalType: 'struct InEuint128',
          components: [
            { name: 'ctHash', type: 'uint256', internalType: 'uint256' },
            { name: 'securityZone', type: 'uint8', internalType: 'uint8' },
            { name: 'utype', type: 'uint8', internalType: 'uint8' },
            { name: 'signature', type: 'bytes', internalType: 'bytes' },
          ],
        },
        {
          name: 'encLow',
          type: 'tuple',
          internalType: 'struct InEuint128',
          components: [
            { name: 'ctHash', type: 'uint256', internalType: 'uint256' },
            { name: 'securityZone', type: 'uint8', internalType: 'uint8' },
            { name: 'utype', type: 'uint8', internalType: 'uint8' },
            { name: 'signature', type: 'bytes', internalType: 'bytes' },
          ],
        },
        { name: 'allowedNodes', type: 'address[]', internalType: 'address[]' },
      ],
      outputs: [],
      stateMutability: 'nonpayable',
    },
  ]

  const toContractInput = (input) => ({
    ctHash: BigInt(input.ctHash),
    securityZone: Number(input.securityZone ?? 0),
    utype: Number(input.utype),
    signature: input.signature,
  })

  const latestBlock = await publicClient.getBlock({ blockTag: 'latest' })
  const fallbackPriorityFeePerGas = 2_000_000n
  const maxPriorityFeePerGas = await publicClient
    .estimateMaxPriorityFeePerGas()
    .catch(() => fallbackPriorityFeePerGas)
  const priorityFeePerGas = maxPriorityFeePerGas > 0n ? maxPriorityFeePerGas : fallbackPriorityFeePerGas
  const baseFeePerGas = latestBlock.baseFeePerGas
  const feeParams =
    baseFeePerGas != null
      ? {
          maxPriorityFeePerGas: priorityFeePerGas,
          maxFeePerGas: baseFeePerGas * 2n + priorityFeePerGas + 1_000_000n,
        }
      : {
          gasPrice: await publicClient.getGasPrice(),
        }

  const txHash = await walletClient.writeContract({
    account: walletClient.account,
    address: payload.promptKeyStoreAddress,
    abi: promptKeyStoreAbi,
    chain: walletClient.chain,
    functionName: 'storeKey',
    args: [
      payload.taskId,
      toContractInput(payload.encryptedHighInput),
      toContractInput(payload.encryptedLowInput),
      payload.allowedNodes,
    ],
    ...feeParams,
  })

  const receipt = await publicClient.waitForTransactionReceipt({ hash: txHash })
  if (receipt.status !== 'success') {
    throw new Error(`PromptKeyStore transaction failed for task ${payload.taskId}`)
  }

  return { txHash }
}

async function main() {
  try {
    const payload = await parseJsonInput()
    let result

    switch (payload.action) {
      case 'decrypt_prompt_key':
        result = await decryptPromptKey(payload)
        break
      case 'encrypt_uint128':
        result = await encryptUint128(payload)
        break
      case 'store_prompt_key':
        result = await storePromptKey(payload)
        break
      default:
        throw new Error(`Unsupported action: ${payload.action}`)
    }

    process.stdout.write(`${JSON.stringify({ ok: true, ...result })}\n`)
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`)
    process.stdout.write(`${JSON.stringify({ ok: false, error: error instanceof Error ? error.message : String(error) })}\n`)
    process.exitCode = 1
  }
}

await main()
