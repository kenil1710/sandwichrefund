import Link from "next/link";
import { ADDR } from "@/lib/deployments";
import { allAttackers, allPools, page, stats } from "@/lib/server";
import { gen, label, short, tokenDec, tokenSym, units } from "@/lib/format";
import { Receipt } from "@/components/Receipt";
import type { Attacker, Case, Page } from "@/lib/types";

export const revalidate = 30;

export default async function Home() {
  let s, cases: Case[] = [], attackers: Attacker[] = [], pools;
  try {
    s = await stats(ADDR.registry);
    // the most recent cases only: one bounded page from the end of the list
    let recentPage: Page<Case>;
    [recentPage, attackers, pools] = await Promise.all([page<Case>(ADDR.registry, "get_cases", [], s.cases - 12, 12), allAttackers(ADDR.registry), allPools(ADDR.registry)]);
    cases = recentPage.items;
  } catch (e) {
    return <><h1>The board is unreadable right now</h1><p className="note warn">Studio Dev did not answer ({String((e as Error)?.message ?? e).slice(0, 140)}). Nothing is shown rather than a guess; reload in a minute.</p></>;
  }
  const c = s.counts;
  const sandwiched = (c["state:SANDWICHED_REFUNDED"] ?? 0) + (c["state:SANDWICHED_UNPAID"] ?? 0);
  const top = [...attackers].sort((a, b) => b.n_cases - a.n_cases).slice(0, 8);
  const recent = [...cases].filter((x) => x.state !== "UNVERIFIABLE").sort((a, b) => b.filed_at - a.filed_at || b.case_id - a.case_id).slice(0, 9);
  const loss = Object.entries(s.loss_total ?? {});
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Live board · canonical contract · Ethereum</p>
      <h1>Sandwiched?<br />The receipt pays you back.</h1>
      <p className="lede">
        A sponsor funds a refund pool for swaps through the routers it covers. Every swap filed is read from Ethereum by GenLayer validators,
        twice, and code decides: a front-run and a back-run by one actor on the victim&apos;s own pool, in the same block, with a profit, is a
        sandwich, and the victim gets the attacker&apos;s profit back in GEN, pushed to the address that sent the swap. Nobody approves anything.
      </p>
      <div className="tiles" role="list">
        <div className="tile" role="listitem"><div className="n">{s.cases}</div><div className="l">cases filed</div></div>
        <div className="tile red" role="listitem"><div className="n">{sandwiched}</div><div className="l">sandwiches detected</div></div>
        <div className="tile mint" role="listitem"><div className="n">{gen(s.refunded_total)}</div><div className="l">GEN refunded</div></div>
        <div className="tile" role="listitem"><div className="n">{c["state:CLEAN"] ?? 0}</div><div className="l">clean</div></div>
        <div className="tile" role="listitem"><div className="n">{c["state:UNCLEAR"] ?? 0}</div><div className="l">unclear</div></div>
        <div className="tile" role="listitem"><div className="n">{s.pools}</div><div className="l">pools ({pools.filter((p) => p.status === "OPEN").length} open)</div></div>
      </div>
      {loss.length > 0 && <p className="small">Attacker profit taken from these victims (the loss estimate): {loss.map(([k, v]) => `${units(v, tokenDec(k.split("|")[1]))} ${tokenSym(k.split("|")[1])}`).join(" · ")}.</p>}

      <h2>Recent receipts</h2>
      <div className="receipts">{recent.map((x) => <Receipt key={x.case_id} c={x} />)}</div>
      <p><Link href="/pools">Every case, pool by pool →</Link></p>

      <h2>Top attackers</h2>
      <div className="scroll">
        <table className="table">
          <thead><tr><th>attacker EOA</th><th>contract</th><th>sandwiches</th><th>refunds caused</th></tr></thead>
          <tbody>
            {top.map((a) => (
              <tr key={a.address}>
                <td><a className="addr" href={`https://etherscan.io/address/${a.address}`}>{short(a.address, 8)}</a> {label(a.address) && <span className="pill">{label(a.address)}</span>}</td>
                <td><a className="addr" href={`https://etherscan.io/address/${a.contract}`}>{short(a.contract, 8)}</a> {label(a.contract) && <span className="pill">{label(a.contract)}</span>}</td>
                <td>{a.n_cases}</td>
                <td>{gen(a.refunds)} GEN</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <h2>How a case is decided</h2>
      <ol className="prose">
        <li>Anyone (usually the keeper) files a victim transaction hash against a pool.</li>
        <li>Every validator reads the transaction, its receipt and every Uniswap Swap log on its pools in that block and the next, from two Ethereum RPCs that must agree; the block must be finalized.</li>
        <li>Code applies the rule: covered router, block range, a canonical pool, one front-run and one back-run by one actor, a positive profit. Anything partial is UNCLEAR, never paid.</li>
        <li>The refund, min(profit × rate, caps, pool balance), is sent to the victim in the same transaction. <Link href="/docs">Every rule →</Link></li>
      </ol>
    </>
  );
}
