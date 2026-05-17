/**
 * CoFHE encrypt bridge — spawnable from Python via subprocess.
 *
 * Matches the working node-reineira cofhe_bridge.mjs encryptUint128 pattern.
 * Uses @cofhe/sdk/node + viem with Arbitrum Sepolia RPC.
 *
 * Usage: npx ts-node scripts/cofhe_encrypt.ts <valueHex> <rpcUrl>
 * Reads private key from BLF_PRIVATE_KEY env var.
 * Prints the handle (ctHash as integer) to stdout.
 */

import { createCofheClient, createCofheConfig } from "@cofhe/sdk/node"
import { Encryptable } from "@cofhe/sdk"
import { chains } from "@cofhe/sdk/chains"
import { createPublicClient, createWalletClient, http } from "viem"
import { privateKeyToAccount } from "viem/accounts"
import { arbitrumSepolia } from "viem/chains"

async function main() {
  const [valueHex, rpcUrl] = process.argv.slice(2)
  const privateKey = process.env.BLF_PRIVATE_KEY

  if (!valueHex || !rpcUrl || !privateKey) {
    process.stderr.write(
      "Usage: BLF_PRIVATE_KEY=0x... ts-node cofhe_encrypt.ts <valueHex> <rpcUrl>\n"
    )
    process.exit(1)
  }

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

  const encrypted = await client
    .encryptInputs([Encryptable.uint128(BigInt(valueHex))])
    .execute()

  process.stdout.write(encrypted[0].ctHash.toString())
}

main().catch((e) => {
  process.stderr.write(e.message + "\n")
  process.exit(1)
})
