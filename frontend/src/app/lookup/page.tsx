import Link from "next/link";
import type { Metadata } from "next";
import { ADDR } from "@/lib/deployments";
import { gateAddress, victimCases } from "@/lib/server";
import { gen, STATE_LABEL } from "@/lib/format";
import { Receipt } from "@/components/Receipt";

export const metadata: Metadata = { title: "Was I sandwiched?" };
export const dynamic = "force-dynamic";

export default async function Lookup({ searchParams }: { searchParams: Promise<{ address?: string }> }) {
  const q = ((await searchParams).address ?? "").trim().toLowerCase();
  const valid = /^0x[0-9a-f]{40}$/.test(q);
  let body: React.ReactNode = null;
  if (q && !valid) body = <p className="note warn">That is not an Ethereum address (0x followed by 40 hex characters).</p>;
  if (valid) {
    try {
      const [g, cases] = await Promise.all([gateAddress(ADDR.gate, q), victimCases(ADDR.registry, q)]);
      body = (
        <>
          <div className="tiles">
            <div className={`tile ${g.state.startsWith("SANDWICHED") ? "red" : g.state === "CLEAN" ? "mint" : ""}`}><div className="n" style={{ fontSize: 22 }}>{STATE_LABEL[g.state] ?? g.state}</div><div className="l">MEVGate summary</div></div>
            <div className="tile"><div className="n">{g.cases}</div><div className="l">cases</div></div>
            <div className="tile red"><div className="n">{g.loss_cases}</div><div className="l">sandwiched</div></div>
            <div className="tile mint"><div className="n">{gen(g.refunded)}</div><div className="l">GEN refunded</div></div>
          </div>
          <p className="small">{g.why}. Counts: {Object.entries(g.counts).filter(([, n]) => n > 0).map(([k, n]) => `${k} ${n}`).join(", ") || "none"}. JSON: <a href={`/api/address?address=${q}`}>/api/address</a> · badge: <a href={`/api/badge?address=${q}`}>/api/badge</a></p>
          {cases.length === 0 ? <p className="note">No swap sent by this address has been filed. That is not the same as clean: the gate says UNVERIFIABLE until a case is decided.</p>
            : <div className="receipts">{cases.map((c) => <Receipt key={c.case_id} c={c} />)}</div>}
        </>
      );
    } catch (e) {
      body = <p className="note warn">Studio Dev did not answer: {String((e as Error)?.message ?? e).slice(0, 160)}</p>;
    }
  }
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Address lookup</p>
      <h1>Was I sandwiched?</h1>
      <p className="lede">Paste the Ethereum address that sent your swap. You see every case filed for it on the canonical contract and what MEVGate makes of them.</p>
      <form className="form" action="/lookup" method="get" role="search">
        <label>Your address<input name="address" defaultValue={q} placeholder="0x…" autoComplete="off" spellCheck={false} /></label>
        <div><button className="btn" type="submit">Look it up</button></div>
      </form>
      {body}
      {!q && <p className="small" style={{ marginTop: 24 }}>Try a real victim from the seeds: <Link href="/lookup?address=0x1ca5e77a3464488d959d8298f593914d5fe30f28">0x1ca5e7…0f28</Link>.</p>}
    </>
  );
}
