/**
 * CoFHE decrypt bridge — spawnable from Python via subprocess.
 *
 * Usage: npx ts-node scripts/cofhe_decrypt.ts <ctHandleHex> <privateKey>
 * Prints the decrypted plaintext (uint128 integer) to stdout.
 */

import { createPublicClient, createWalletClient, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { arbitrumSepolia } from "viem/chains";
import { createCofheClient } from "@cofhe/sdk/web";

async function main() {
  const [ctHandleHex, privateKey] = process.argv.slice(2);
  if (!ctHandleHex || !privateKey) {
    process.stderr.write("Usage: ts-node cofhe_decrypt.ts <ctHandleHex> <privateKey>\n");
    process.exit(1);
  }

  const account = privateKeyToAccount(privateKey as `0x${string}`);
  const publicClient = createPublicClient({
    chain: arbitrumSepolia,
    transport: http(),
  });
  const walletClient = createWalletClient({
    account,
    chain: arbitrumSepolia,
    transport: http(),
  });

  const client = await createCofheClient({
    publicClient,
    walletClient,
  });
  await client.connect(publicClient, walletClient);

  const result = await client
    .decryptForView(BigInt(ctHandleHex))
    .withPermit(await client.permits.getOrCreateSelfPermit())
    .execute();

  process.stdout.write(result.toString());
}

main().catch((e) => {
  process.stderr.write(e.message + "\n");
  process.exit(1);
});
