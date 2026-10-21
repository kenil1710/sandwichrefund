"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import { send, viewOf } from "@/lib/contract";
import { regAddr, type Reg } from "@/lib/deployments";
import type { Case, Pool, TxProgress } from "@/lib/types";

const ETH_RPC = "https://rpc.mevblocker.io";

/** The victim of a transaction (its sender), read from Ethereum, so the refund's external message can be funded. */
async function senderOf(hash: string): Promise<string> {
  const r = await fetch(ETH_RPC, { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getTransactionByHash", params: [hash] }) });
  const j = await r.json();
  if (!j.result?.from) throw new Error("Ethereum does not know this transaction (or the RPC did not answer).");
  return String(j.result.from).toLowerCase();
}

export function PoolActions({ reg, pool }: { reg: Reg; pool: Pool }) {
  const w = useWallet();
  const router = useRouter();
  const [hash, setHash] = useState("");
  const [amount, setAmount] = useState("0.1");
  const [deadline, setDeadline] = useState("");
  const [p, setP] = useState<TxProgress | null>(null);
  const addr = regAddr(reg);
  const now = Math.floor(Date.now() / 1000);
  const open = pool.status === "OPEN" && now <= pool.claim_deadline;
  const recovery = pool.status === "OPEN" && now > pool.claim_deadline && pool.pending > 0 && now <= pool.recovery_deadline;
  const need = !w.account ? "Connect a wallet to act on this pool." : w.onWrongNetwork ? "Switch your wallet to Studio Dev." : "";

  async function file() {
    if (!w.account) return;
    const h = hash.trim().toLowerCase();
    if (!/^0x[0-9a-f]{64}$/.test(h)) { setP({ phase: "failed", hash: null, message: "A transaction hash is 0x and 64 hex characters." }); return; }
    let victim: string;
    try { victim = await senderOf(h); } catch (e) { setP({ phase: "failed", hash: null, message: String((e as Error).message) }); return; }
    const r = await send<{ state: string }>(w.account, addr, "file_case", [pool.pool_id, "ethereum", h], 0n, {
      payee: victim, onProgress: setP,
      confirm: async () => (await viewOf<Case>(addr, "get_pool_case", [pool.pool_id, "ethereum", h])).found === true,
    });
    if (r.kind === "ok") router.push(`/case/ethereum/${h}${reg === "demo" ? "?reg=demo" : ""}`);
  }
  async function topUp() {
    if (!w.account) return;
    const wei = BigInt(Math.round(Number(amount) * 1e6)) * 10n ** 12n;
    await send(w.account, addr, "top_up", [pool.pool_id], wei, { onProgress: setP });
    router.refresh();
  }
  async function extend() {
    if (!w.account) return;
    const t = Math.floor(new Date(deadline).getTime() / 1000);
    if (!t) { setP({ phase: "failed", hash: null, message: "Pick a date and time." }); return; }
    await send(w.account, addr, "extend", [pool.pool_id, t], 0n, { onProgress: setP });
    router.refresh();
  }
  async function close() {
    if (!w.account) return;
    await send(w.account, addr, "close_pool", [pool.pool_id], 0n, { payee: pool.sponsor, onProgress: setP,
      confirm: async () => (await viewOf<Pool>(addr, "get_pool", [pool.pool_id, 0])).status === "CLOSED" });
    router.refresh();
  }
  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Act on this pool</h3>
      {need && <p className="note">{need}</p>}
      {open ? (
        <>
          <label className="small" htmlFor="hash"><b>File a case</b> (anyone): an Ethereum swap transaction hash</label>
          <input id="hash" value={hash} onChange={(e) => setHash(e.target.value)} placeholder="0x…" spellCheck={false} />
          <p><button className="btn" onClick={() => void file()} disabled={!w.account || w.onWrongNetwork}>File it</button></p>
          <p className="small">Your wallet funds the refund&apos;s message to the victim; if the swap was sandwiched the victim is paid in the same transaction.</p>
          <label className="small" htmlFor="amt"><b>Top up</b> (anyone, adds only), GEN</label>
          <input id="amt" value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
          <p><button className="btn ghost" onClick={() => void topUp()} disabled={!w.account || w.onWrongNetwork}>Top up</button></p>
          {w.account?.toLowerCase() === pool.sponsor && <>
            <label className="small" htmlFor="dl"><b>Extend</b> the claim deadline (sponsor only, later only)</label>
            <input id="dl" type="datetime-local" value={deadline} onChange={(e) => setDeadline(e.target.value)} />
            <p><button className="btn ghost" onClick={() => void extend()}>Extend</button></p>
          </>}
        </>
      ) : recovery ? (
        <>
          <p>The claim period is over. {pool.pending} case(s) left UNVERIFIABLE for a transient reason may be filed again until {new Date(pool.recovery_deadline * 1000).toISOString().slice(11, 16)} UTC; the pool closes after that, or as soon as none remain.</p>
          <label className="small" htmlFor="hash2"><b>Retry a pending case</b></label>
          <input id="hash2" value={hash} onChange={(e) => setHash(e.target.value)} placeholder="0x…" spellCheck={false} />
          <p><button className="btn" onClick={() => void file()} disabled={!w.account || w.onWrongNetwork}>File it again</button></p>
        </>
      ) : pool.status === "OPEN" ? (
        <>
          <p>The claim period is over. Anyone can close the pool: the remaining {Number(pool.balance) / 1e18} GEN goes back to the sponsor.</p>
          <p><button className="btn" onClick={() => void close()} disabled={!w.account || w.onWrongNetwork}>Close pool</button></p>
        </>
      ) : <p>Closed. Every GEN of this pool was refunded or returned to the sponsor.</p>}
      <TxStatus p={p} />
    </div>
  );
}
