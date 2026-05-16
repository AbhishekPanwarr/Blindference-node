/**
 * CoFHE encrypt bridge — spawnable from Python via subprocess.
 *
 * Usage: npx ts-node scripts/cofhe_encrypt.ts <valueHex> <privateKey>
 * Prints the handle (uint256) as a hex integer to stdout.
 */

import { createPublicClient, createWalletClient, http } from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { arbitrumSepolia } from "viem/chains";
import { createCofheClient } from "@cofhe/sdk/web";
import { EncryptionTypes } from "@cofhe/sdk";

async function main() {
  const [valueHex, privateKey] = process.argv.slice(2);
  if (!valueHex || !privateKey) {
    process.stderr.write("Usage: ts-node cofhe_encrypt.ts <valueHex> <privateKey>\n");
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

  const encrypted = await client.encrypt(
    BigInt(valueHex),
    EncryptionTypes.uint128
  );

  process.stdout.write(encrypted.data!.toString());
}

main().catch((e) => {
  process.stderr.write(e.message + "\n");
  process.exit(1);
});
