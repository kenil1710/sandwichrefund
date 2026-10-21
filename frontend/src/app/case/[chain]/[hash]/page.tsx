import Link from "next/link";
import type { Metadata } from "next";
import { asReg, CANONICAL, gateAddr, regAddr, STUDIO_EXPLORER, SITE } from "@/lib/deployments";
import { filingTxs, gateCase, getCase, pool as getPool } from "@/lib/server";
import { ETHERSCAN, REASON_TEXT, STATE_LABEL, gen, label, routerName, short, tokenDec, tokenSym, units } from "@/lib/format";
import { Receipt } from "@/components/Receipt";
import { Timeline } from "@/components/Timeline";

export const revalidate = 30;
type P = { params: Promise<{ chain: string; hash: string }>; searchParams: Promise<{ reg?: string }> };

export async function generateMetadata({ params }: P): Promise<Metadata> {
  const { hash } = await params;
  return { title: `Case ${hash.slice(0, 10)}` };
}

export default async function CasePage({ params, searchParams }: P) {
  const { chain, hash } = await params;
  const reg = asReg((await searchParams).reg);
  const h = hash.toLowerCase();
  let c, g, txs: Record<string, string> = {};
  try {
    [c, txs] = await Promise.all([getCase(regAddr(reg), chain, h), filingTxs()]);
    // the gate is asked about the pool that decided this case, bound to that pool's sponsor
    const pid = c.found ? c.pool_id : reg === "demo" ? 1 : CANONICAL.pool_id;
    const sponsor = c.found ? (await getPool(regAddr(reg), pid)).sponsor : CANONICAL.sponsor;
    g = await gateCase(gateAddr(reg), pid, sponsor, chain, h);
  }
  catch (e) { return <><h1>Unreadable</h1><p className="note warn">Studio Dev did not answer: {String((e as Error)?.message ?? e).slice(0, 160)}</p></>; }
  if (!c.found) {
    return (
      <>
        <p className="kicker" style={{ marginTop: 28 }}>Case · {chain}</p>
        <h1 style={{ fontSize: 40, wordBreak: "break-all" }}>{short(h, 10)}</h1>
        <p className="note">Nobody has filed this transaction {reg === "demo" ? "on the demo contract" : "yet"}. The gate reads it as <b>{g.state}</b>: {g.why}. Anyone can file it against an open pool from the <Link href="/pools">pools page</Link>.</p>
      </>
    );
  }
  const f = c.facts ?? {};
  const sandwiched = c.state.startsWith("SANDWICHED");
  const filed = txs[`${c.pool_id}:${c.tx_hash}`];
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Case #{c.case_id} · pool {c.pool_id}{reg === "demo" ? " · demo contract" : ""}</p>
      <h1 style={{ fontSize: "clamp(32px, 6vw, 56px)" }}>{STATE_LABEL[c.state] ?? c.state}</h1>
      <p className="lede">{REASON_TEXT[c.reason] ?? c.reason}{c.detail ? ` (${c.detail})` : ""}</p>
      <div className="row2">
        <div>
          <h2 style={{ marginTop: 8 }}>Block timeline</h2>
          {f.kind ? <Timeline c={c} /> : <p className="note">No single-pool swap to draw for this case ({c.reason}).</p>}
          <h2>Decoded</h2>
          <div className="scroll">
            <table className="table">
              <tbody>
                <tr><th>victim tx</th><td><a className="addr" href={`${ETHERSCAN}/tx/${c.tx_hash}`}>{c.tx_hash}</a></td></tr>
                <tr><th>block / index</th><td>{c.block} / {c.tx_index}</td></tr>
                <tr><th>victim (tx.from)</th><td><Link className="addr" href={`/lookup?address=${c.victim}`}>{c.victim}</Link></td></tr>
                <tr><th>router (tx.to)</th><td><span className="addr">{c.router}</span> {routerName(c.router)}</td></tr>
                {c.dex_pool && <tr><th>pool</th><td><a className="addr" href={`${ETHERSCAN}/address/${c.dex_pool}`}>{c.dex_pool}</a> {f.kind}</td></tr>}
                {f.token_in && <tr><th>victim paid / got</th><td>{tokenSym(f.token_in)} → {tokenSym(f.token_out ?? "")}</td></tr>}
                {f.front_tx && <tr><th>front-run</th><td><a className="addr" href={`${ETHERSCAN}/tx/${f.front_tx}`}>{short(f.front_tx, 10)}</a> idx {f.front_index}</td></tr>}
                {f.back_tx && <tr><th>back-run</th><td><a className="addr" href={`${ETHERSCAN}/tx/${f.back_tx}`}>{short(f.back_tx, 10)}</a> idx {f.back_index}</td></tr>}
                {f.attacker_eoa && <tr><th>attacker EOA</th><td><a className="addr" href={`${ETHERSCAN}/address/${f.attacker_eoa}`}>{f.attacker_eoa}</a> {label(f.attacker_eoa)}</td></tr>}
                {f.attacker_contract && <tr><th>attacker contract</th><td><a className="addr" href={`${ETHERSCAN}/address/${f.attacker_contract}`}>{f.attacker_contract}</a> {label(f.attacker_contract)}</td></tr>}
                {sandwiched && <tr><th>attacker profit (loss estimate)</th><td>{units(c.loss, tokenDec(c.profit_token))} {tokenSym(c.profit_token)}</td></tr>}
                {sandwiched && <tr><th>refund due / paid</th><td>{gen(c.refund_due)} / <b>{gen(c.refund_paid)} GEN</b> ({c.limit})</td></tr>}
                <tr><th>verdict / reason</th><td>{c.verdict} / {c.reason}</td></tr>
                <tr><th>filed by</th><td><span className="addr">{c.filer}</span> · attempts {c.attempts}{filed && <> · <a href={`${STUDIO_EXPLORER}/tx/${filed}`}>GenLayer tx {short(filed, 8)}</a></>}</td></tr>
                <tr><th>MEVGate (pool {g.pool_id}, its sponsor)</th><td><span className={`pill ${g.state}`}>{g.state}</span> clean={String(g.clean)} refunded={String(g.refunded)}</td></tr>
                {(c.n_decisions ?? 1) > 1 && <tr><th>decisions</th><td>{c.decisions?.map((d) => <div key={d.case_id}>pool {d.pool_id}: {d.state} {gen(d.refund_paid)} GEN</div>)}</td></tr>}
              </tbody>
            </table>
          </div>
          <p className="small">JSON: <a href={`/api/case?chain=${chain}&hash=${c.tx_hash}${reg === "demo" ? "&reg=demo" : ""}`}>/api/case</a> · badge: <a href={`/api/badge?chain=${chain}&hash=${c.tx_hash}`}>/api/badge</a></p>
          <p><img src={`/api/badge?chain=${chain}&hash=${c.tx_hash}${reg === "demo" ? "&reg=demo" : ""}`} alt={`SandwichRefund badge: ${c.state}`} height={20} /></p>
          <p className="small mono">{`![SandwichRefund](${SITE}/api/badge?chain=${chain}&hash=${c.tx_hash})`}</p>
        </div>
        <div><Receipt c={c} reg={reg} big link={false} /></div>
      </div>
    </>
  );
}
