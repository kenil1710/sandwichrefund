"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useWallet } from "@/components/WalletProvider";
import { TxStatus } from "@/components/TxStatus";
import { send, viewOf } from "@/lib/contract";
import { regAddr, type Reg } from "@/lib/deployments";
import { gen } from "@/lib/format";
import canonical from "@/lib/pool_canonical.json";
import type { Page, Pool, TxProgress } from "@/lib/types";

const toWei = (g: string) => BigInt(Math.round(Number(g || "0") * 1e6)) * 10n ** 12n;

export function SponsorForm() {
  const w = useWallet();
  const [reg, setReg] = useState<Reg>("demo");
  const [name, setName] = useState("My wallet's swap refunds");
  const [routers, setRouters] = useState(canonical.routers.map((r) => `${r.address} ${r.name}`).join("\n"));
  const [kinds, setKinds] = useState({ V2: true, V3: true });
  const [start, setStart] = useState(String(canonical.ranges[0].start_block));
  const [end, setEnd] = useState(String(canonical.ranges[0].end_block));
  const [rates, setRates] = useState(canonical.rates.map((r) => `${r.token} ${r.num}/${r.den} ${r.symbol} ${r.decimals}`).join("\n"));
  const [maxSwap, setMaxSwap] = useState("0.05");
  const [maxVictim, setMaxVictim] = useState("0.1");
  const [claim, setClaim] = useState("3600");
  const [value, setValue] = useState("0.5");
  const [p, setP] = useState<TxProgress | null>(null);
  const [mine, setMine] = useState<Pool[]>([]);

  useEffect(() => {
    if (!w.account) return;
    void (async () => {
      const out: Pool[] = [];
      for (const r of ["canonical", "demo"] as Reg[]) {
        for (let off = 0; ; ) {
          const pg = await viewOf<Page<Pool>>(regAddr(r), "get_pools", [off, 50, Math.floor(Date.now() / 1000)]).catch(() => null);
          if (!pg) break;
          out.push(...pg.items.filter((x) => x.sponsor === w.account!.toLowerCase()).map((x) => ({ ...x, meta: { ...x.meta, _reg: r } })));
          if (pg.next_offset < 0) break;
          off = pg.next_offset;
        }
      }
      setMine(out);
    })();
  }, [w.account, p?.phase]);

  async function create() {
    if (!w.account) return;
    const rl = routers.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [address, ...rest] = l.split(/\s+/); return { chain: "ethereum", address, name: rest.join(" ") }; });
    const rt = rates.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [token, frac, symbol, dec] = l.split(/\s+/); const [num, den] = (frac ?? "1/1").split("/"); return { chain: "ethereum", token, num, den: den ?? "1", symbol: symbol ?? "", decimals: Number(dec ?? 18) }; });
    const k = Object.entries(kinds).filter(([, v]) => v).map(([x]) => x);
    await send(w.account, regAddr(reg), "create_pool", [name, JSON.stringify(["ethereum"]), JSON.stringify(rl), JSON.stringify(k),
      JSON.stringify([{ chain: "ethereum", start_block: Number(start), end_block: Number(end) }]), JSON.stringify(rt),
      toWei(maxSwap), toWei(maxVictim), Number(claim), "{}"], toWei(value), { onProgress: setP });
  }

  return (
    <div className="row2">
      <div className="form" aria-label="Create a pool">
        <label>Contract
          <select value={reg} onChange={(e) => setReg(e.target.value as Reg)}>
            <option value="demo">Demo (claim period from 1 minute)</option>
            <option value="canonical">Canonical (claim period from 1 hour)</option>
          </select>
        </label>
        <label>Name<input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label>Covered routers (one per line: address name)<textarea value={routers} onChange={(e) => setRouters(e.target.value)} rows={6} /></label>
        <fieldset style={{ border: "2px solid var(--ink)", padding: 10 }}>
          <legend className="small">Pool types</legend>
          <label style={{ display: "inline-flex", gap: 6, marginRight: 16 }}><input type="checkbox" style={{ width: "auto" }} checked={kinds.V2} onChange={(e) => setKinds({ ...kinds, V2: e.target.checked })} />Uniswap V2-style</label>
          <label style={{ display: "inline-flex", gap: 6 }}><input type="checkbox" style={{ width: "auto" }} checked={kinds.V3} onChange={(e) => setKinds({ ...kinds, V3: e.target.checked })} />Uniswap V3-style</label>
        </fieldset>
        <div className="row2" style={{ gap: 12 }}>
          <label>Start block<input value={start} onChange={(e) => setStart(e.target.value)} inputMode="numeric" /></label>
          <label>End block<input value={end} onChange={(e) => setEnd(e.target.value)} inputMode="numeric" /></label>
        </div>
        <label>Rates (one per line: token num/den symbol decimals; refund = profit × num ÷ den GEN wei per token wei)<textarea value={rates} onChange={(e) => setRates(e.target.value)} rows={4} /></label>
        <div className="row2" style={{ gap: 12 }}>
          <label>Max per swap (GEN)<input value={maxSwap} onChange={(e) => setMaxSwap(e.target.value)} inputMode="decimal" /></label>
          <label>Max per victim (GEN)<input value={maxVictim} onChange={(e) => setMaxVictim(e.target.value)} inputMode="decimal" /></label>
        </div>
        <div className="row2" style={{ gap: 12 }}>
          <label>Claim period (seconds)<input value={claim} onChange={(e) => setClaim(e.target.value)} inputMode="numeric" /></label>
          <label>Pool (GEN sent now)<input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" /></label>
        </div>
        <div><button className="btn" onClick={() => void create()} disabled={!w.account || w.onWrongNetwork}>{w.account ? "Create pool and lock GEN" : "Connect a wallet first"}</button></div>
        <TxStatus p={p} />
        <p className="small">A refused pool (bad terms) is not lost: the GEN is credited back and you withdraw it with withdraw_refund.</p>
      </div>
      <div>
        <h3 style={{ marginTop: 0 }}>Your pools</h3>
        {!w.account ? <p className="small">Connect to see the pools you sponsor.</p> : mine.length === 0 ? <p className="small">None yet.</p> :
          <ul>{mine.map((x) => <li key={`${x.meta._reg}-${x.pool_id}`}><Link href={`/pool/${x.pool_id}${x.meta._reg === "demo" ? "?reg=demo" : ""}`}>#{x.pool_id} {x.name}</Link> · {x.status}{x.due ? " · due to close" : ""} · balance {gen(x.balance)} GEN · {x.n_cases} cases</li>)}</ul>}
        <p className="small">Top up, extend and close are on each pool&apos;s page.</p>
      </div>
    </div>
  );
}
