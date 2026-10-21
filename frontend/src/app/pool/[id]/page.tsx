import Link from "next/link";
import type { Metadata } from "next";
import { asReg, regAddr, STUDIO_EXPLORER } from "@/lib/deployments";
import { page, pool as getPool } from "@/lib/server";
import type { Case, Page } from "@/lib/types";
import { gen, short, units, when } from "@/lib/format";
import { Receipt } from "@/components/Receipt";
import { PoolActions } from "./PoolActions";

export const revalidate = 30;
type P = { params: Promise<{ id: string }>; searchParams: Promise<{ reg?: string; state?: string; offset?: string }> };
const PER_PAGE = 50;
export async function generateMetadata({ params }: P): Promise<Metadata> { return { title: `Pool ${(await params).id}` }; }

export default async function PoolPage({ params, searchParams }: P) {
  const id = Number((await params).id);
  const sp = await searchParams;
  const reg = asReg(sp.reg);
  const offset = Math.max(0, Number(sp.offset ?? 0) || 0);
  let p, pg: Page<Case>;
  try { [p, pg] = await Promise.all([getPool(regAddr(reg), id), page<Case>(regAddr(reg), "get_pool_cases", [id], offset, PER_PAGE)]); }
  catch (e) { return <><h1>Pool {id}</h1><p className="note warn">Studio Dev did not answer: {String((e as Error)?.message ?? e).slice(0, 160)}</p></>; }
  if (!p.found) return <><h1>Pool {id}</h1><p className="note">No such pool.</p></>;
  const cases = pg.items;
  const states = [...new Set(cases.map((c) => c.state))];
  const q = (o: number) => `/pool/${id}?offset=${o}${reg === "demo" ? "&reg=demo" : ""}`;
  const shown = sp.state ? cases.filter((c) => c.state === sp.state) : cases;
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Pool #{p.pool_id}{reg === "demo" ? " · demo contract" : ""} · <span className={`pill ${p.status}`}>{p.status}</span></p>
      <h1 style={{ fontSize: "clamp(30px, 5vw, 52px)" }}>{p.name}</h1>
      <div className="tiles">
        <div className="tile"><div className="n">{gen(p.funded)}</div><div className="l">GEN funded</div></div>
        <div className="tile mint"><div className="n">{gen(p.refunded)}</div><div className="l">refunded ({p.n_refunded})</div></div>
        <div className="tile"><div className="n">{gen(p.balance)}</div><div className="l">balance</div></div>
        <div className="tile"><div className="n">{gen(p.returned)}</div><div className="l">returned to sponsor</div></div>
        <div className="tile"><div className="n">{p.n_cases}</div><div className="l">cases</div></div>
      </div>
      <div className="row2">
        <div>
          <h2 style={{ marginTop: 0 }}>Frozen terms</h2>
          <div className="scroll"><table className="table"><tbody>
            <tr><th>sponsor</th><td className="addr">{p.sponsor}</td></tr>
            <tr><th>chains / kinds</th><td>{p.chains.join(", ")} · {p.kinds.join(", ")}</td></tr>
            <tr><th>blocks</th><td>{p.ranges.map((r) => `${r.chain} ${r.start_block}–${r.end_block}`).join("; ")}</td></tr>
            <tr><th>rates</th><td>{p.rates.map((r) => <div key={r.token}>{r.symbol || short(r.token)}: {r.num}/{r.den} GEN wei per wei ({units((10n ** BigInt(r.decimals) * BigInt(r.num)) / BigInt(r.den))} GEN per {r.symbol || "token"})</div>)}</td></tr>
            <tr><th>max per swap / victim</th><td>{gen(p.max_per_swap)} / {gen(p.max_per_victim)} GEN</td></tr>
            <tr><th>claim period</th><td>{p.claim_period_s} s · deadline {when(p.claim_deadline)}{p.claim_deadline !== p.original_deadline && ` (extended from ${when(p.original_deadline)})`}</td></tr>
            <tr><th>recovery window</th><td>until {when(p.recovery_deadline)} · {p.pending} case(s) pending{p.n_expired ? ` · ${p.n_expired} expired at close` : ""}</td></tr>
            <tr><th>closed</th><td>{p.closed_at ? `${when(p.closed_at)} by ${short(p.closed_by)}` : "not yet"}</td></tr>
          </tbody></table></div>
          <h3>Routers</h3>
          <ul className="small">{p.routers.map((r) => <li key={r.address}><span className="addr">{r.address}</span> {r.name}</li>)}</ul>
          <h3>History</h3>
          <ul className="small mono">{p.history.map((h, i) => <li key={i}>{when(Number(h.at))} {String(h.what)} {h.value ? gen(String(h.value)) + " GEN" : ""}{h.to ? " → " + when(Number(h.to)) : ""}</li>)}</ul>
        </div>
        <div><PoolActions reg={reg} pool={p} /></div>
      </div>
      <h2>Cases</h2>
      <p className="small">Filter: <Link href={`/pool/${id}${reg === "demo" ? "?reg=demo" : ""}`}>all ({cases.length})</Link>{states.map((s) => <span key={s}> · <Link href={`/pool/${id}?state=${s}${reg === "demo" ? "&reg=demo" : ""}`}>{s} ({cases.filter((c) => c.state === s).length})</Link></span>)}</p>
      <p className="small">Cases {offset + 1}-{offset + cases.length} of {pg.total}{offset > 0 && <> · <Link href={q(Math.max(0, offset - PER_PAGE))}>previous {PER_PAGE}</Link></>}{pg.next_offset > 0 && <> · <Link href={q(pg.next_offset)}>next {PER_PAGE}</Link></>}</p>
      <div className="receipts">{shown.map((c) => <Receipt key={c.case_id} c={c} reg={reg} />)}</div>
      <p className="small">Contract <a className="mono" href={`${STUDIO_EXPLORER}/address/${regAddr(reg)}`}>{regAddr(reg)}</a></p>
    </>
  );
}
