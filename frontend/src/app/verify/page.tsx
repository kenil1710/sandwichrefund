import type { Metadata } from "next";
import { verifyAll } from "@/lib/verify";
import { COMMIT, REPO, STUDIO_EXPLORER } from "@/lib/deployments";
import { short } from "@/lib/format";

export const metadata: Metadata = { title: "Verify" };
export const revalidate = 300;

export default async function Verify() {
  const rows = await verifyAll();
  const ok = rows.every((r) => r.identical);
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Source match, read live</p>
      <h1>{ok ? "Byte-identical." : "Mismatch."}</h1>
      <p className="lede">The code of each contract is read back from Studio Dev (gen_getContractCode) and compared byte for byte with <code>build/*.py</code> on GitHub at the deploy commit <a className="mono" href={`${REPO}/commit/${COMMIT}`}>{COMMIT.slice(0, 7)}</a>. All four were deployed from that one commit. Offline, <code>node tools/verify_source.mjs</code> does the same against your clone.</p>
      <div className="scroll"><table className="table"><thead><tr><th>contract</th><th>address</th><th>file</th><th>bytes</th><th>sha256 on chain</th><th>sha256 on GitHub</th><th>result</th></tr></thead><tbody>
        {rows.map((r) => <tr key={r.name}><td>{r.name}</td><td><a className="mono small" href={`${STUDIO_EXPLORER}/address/${r.address}`}>{short(r.address)}</a></td><td className="mono small"><a href={`${REPO}/blob/${r.commit}/${r.file}`}>{r.file}</a></td><td>{r.bytes}</td><td className="mono small">{r.onchain_sha256.slice(0, 16)}</td><td className="mono small">{r.github_sha256.slice(0, 16)}</td><td className={r.identical ? "ok" : "bad"}>{r.identical ? "identical" : r.error || "DIFFERS"}</td></tr>)}
      </tbody></table></div>
      <p className="small">JSON: <a href="/api/verify">/api/verify</a></p>
    </>
  );
}
