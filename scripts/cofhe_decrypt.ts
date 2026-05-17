/**
 * CoFHE decrypt bridge — spawnable from Python via subprocess.
 *
 * Matches the working node-reineira cofhe_bridge.mjs decryptPromptKey pattern.
 * Uses @cofhe/sdk/node + viem with Arbitrum Sepolia RPC.
 *
 * Usage: npx ts-node scripts/cofhe_decrypt.ts <ctHandleHex> <rpcUrl>
 * Reads private key from BLF_PRIVATE_KEY env var.
 * Prints the decrypted plaintext (integer) to stdout.
 */

import { createCofheClient, createCofheConfig } from "@cofhe/sdk/node"
import { FheTypes } from "@cofhe/sdk"
import { chains } from "@cofhe/sdk/chains"
import { createPublicClient, createWalletClient, http } from "viem"
import { privateKeyToAccount } from "viem/accounts"
import { arbitrumSepolia } from "viem/chains"

async function main() {
  const [ctHandleHex, rpcUrl] = process.argv.slice(2)
  const privateKey = process.env.BLF_PRIVATE_KEY

  if (!ctHandleHex || !rpcUrl || !privateKey) {
    process.stderr.write(
      "Usage: BLF_PRIVATE_KEY=0x... ts-node cofhe_decrypt.ts <ctHandleHex> <rpcUrl>\n"
    )
    process.exit(1)
  }

  const chainId = 421614 // Arbitrum Sepolia
  const account = privateKeyToAccount(privateKey as `0x${string}`)

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
  })
  const client = createCofheClient(config)
  await client.connect(publicClient, walletClient)

  const permit = await client.permits.getOrCreateSelfPermit()

  const result = await client
    .decryptForView(BigInt(ctHandleHex), FheTypes.Uint128)
    .withPermit(permit)
    .execute()

  process.stdout.write(result.toString())
}

main().catch((e) => {
  process.stderr.write(e.message + "\n")
  process.exit(1)
})
