import "server-only";
import { createHash } from "node:crypto";
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import { CONTRACTS, REPO } from "./deployments";

const client = createClient({ chain: studioDevnet });
const sha = (b: Buffer) => createHash("sha256").update(b).digest("hex");

export interface VerifyRow { name: string; address: string; commit: string; file: string; bytes: number; onchain_sha256: string; github_sha256: string; recorded_sha256: string; identical: boolean; error: string }

/** Each deployed contract's code read back from Studio Dev, compared byte for byte with the build file on GitHub at the deploy commit. */
export async function verifyAll(): Promise<VerifyRow[]> {
  const raw = REPO.replace("https://github.com/", "https://raw.githubusercontent.com/");
  return Promise.all(Object.entries(CONTRACTS).map(async ([name, c]) => {
    const row: VerifyRow = { name, address: c.address, commit: c.commit, file: c.file, bytes: 0, onchain_sha256: "", github_sha256: "", recorded_sha256: c.sha256, identical: false, error: "" };
    try {
      let code = "";
      for (let i = 0; i < 4 && !code; i++) { try { code = String(await client.getContractCode(c.address as `0x${string}`)); } catch { await new Promise((r) => setTimeout(r, 1500)); } }
      const onchain = Buffer.from(code, "utf8");
      const gh = Buffer.from(await (await fetch(`${raw}/${c.commit}/${c.file}`, { next: { revalidate: 3600 } })).arrayBuffer());
      row.bytes = onchain.length;
      row.onchain_sha256 = sha(onchain);
      row.github_sha256 = sha(gh);
      row.identical = onchain.length > 0 && onchain.equals(gh) && row.onchain_sha256 === c.sha256;
    } catch (e) { row.error = String((e as Error)?.message ?? e).slice(0, 160); }
    return row;
  }));
}
