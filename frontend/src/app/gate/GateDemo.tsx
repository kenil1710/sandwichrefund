"use client";
import { useState } from "react";
import { viewOf, send } from "@/lib/contract";
import { CANONICAL, gateAddr, type Reg } from "@/lib/deployments";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import type { GateAddress, GateCase, TxProgress } from "@/lib/types";

export function GateDemo() {
  const w = useWallet();
  const [reg, setReg] = useState<Reg>("canonical");
  const [q, setQ] = useState("");
  const [pool, setPool] = useState(String(CANONICAL.pool_id));
  const [sponsor, setSponsor] = useState(CANONICAL.sponsor);
  const [out, setOut] = useState<GateCase | GateAddress | null>(null);
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [p, setP] = useState<TxProgress | null>(null);
  const v = q.trim().toLowerCase();
  const isHash = /^0x[0-9a-f]{64}$/.test(v), isAddr = /^0x[0-9a-f]{40}$/.test(v);
  async function ask() {
    setErr(""); setOut(null); setBusy(true);
    try {
      if (isHash) setOut(await viewOf<GateCase>(gateAddr(reg), "check_case", [Number(pool), sponsor.trim().toLowerCase(), "ethereum", v]));
      else if (isAddr) setOut(await viewOf<GateAddress>(gateAddr(reg), "check_address", [Number(pool), sponsor.trim().toLowerCase(), v]));
      else setErr("Paste a transaction hash (66 characters) or an address (42).");
    } catch (e) { setErr(String((e as Error).message)); } finally { setBusy(false); }
  }
  async function attest() {
    if (!w.account || !isHash) return;
    await send(w.account, gateAddr(reg), "attest_case", [Number(pool), sponsor.trim().toLowerCase(), "ethereum", v], 0n, { onProgress: setP });
  }
  return (
    <div className="card" style={{ marginTop: 20 }}>
      <div className="form" style={{ maxWidth: "none" }}>
        <label>Gate
          <select value={reg} onChange={(e) => setReg(e.target.value as Reg)}><option value="canonical">MEVGate (canonical contract)</option><option value="demo">MEVGateDemo (demo contract)</option></select>
        </label>
        <label>Pool id<input value={pool} onChange={(e) => setPool(e.target.value)} inputMode="numeric" /></label>
        <label>Its sponsor (the address you trust)<input value={sponsor} onChange={(e) => setSponsor(e.target.value)} spellCheck={false} /></label>
        <label>Transaction hash or address<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="0x…" spellCheck={false} /></label>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <button className="btn" onClick={() => void ask()} disabled={busy}>{busy ? "Reading…" : "Ask the gate"}</button>
          {isHash && <button className="btn ghost" onClick={() => void attest()} disabled={!w.account || w.onWrongNetwork}>Attest on chain</button>}
        </div>
      </div>
      {err && <p className="note warn">{err}</p>}
      {out && <pre className="mono small" style={{ whiteSpace: "pre-wrap", wordBreak: "break-all" }} aria-live="polite">{JSON.stringify(out, null, 2)}</pre>}
      <TxStatus p={p} />
    </div>
  );
}
