import Link from "next/link";
import type { Metadata } from "next";
import { ADDR } from "@/lib/deployments";
import { allPools } from "@/lib/server";
import { gen, when } from "@/lib/format";
import type { Pool } from "@/lib/types";

export const metadata: Metadata = { title: "Pools" };
export const revalidate = 30;

function Rows({ pools, reg }: { pools: Pool[]; reg: string }) {
  return (
    <div className="scroll">
      <table className="table">
        <thead><tr><th>pool</th><th>status</th><th>blocks</th><th>routers</th><th>cases</th><th>funded</th><th>refunded</th><th>returned</th><th>claim deadline</th></tr></thead>
        <tbody>
          {pools.map((p) => (
            <tr key={p.pool_id}>
              <td><Link href={`/pool/${p.pool_id}${reg === "demo" ? "?reg=demo" : ""}`}>#{p.pool_id} {p.name}</Link></td>
              <td><span className={`pill ${p.status}`}>{p.status}</span>{p.due && <span className="pill">due: {p.due}</span>}</td>
              <td className="mono small">{p.ranges.map((r) => `${r.start_block}-${r.end_block}`).join(", ")}</td>
              <td>{p.routers.length}</td>
              <td>{p.n_cases} ({p.n_refunded} refunded{p.n_unpaid ? `, ${p.n_unpaid} unpaid` : ""})</td>
              <td>{gen(p.funded)}</td><td>{gen(p.refunded)}</td><td>{gen(p.returned)}</td>
              <td className="small">{when(p.claim_deadline)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function Pools() {
  let can: Pool[] = [], demo: Pool[] = [];
  try { [can, demo] = await Promise.all([allPools(ADDR.registry), allPools(ADDR.registryDemo)]); }
  catch (e) { return <><h1>Pools</h1><p className="note warn">Studio Dev did not answer: {String((e as Error)?.message ?? e).slice(0, 160)}</p></>; }
  return (
    <>
      <h1>Pools</h1>
      <p className="lede">Each pool is a sponsor&apos;s frozen promise: these routers, these blocks, this rate, these caps. Sponsors can only top up or extend.</p>
      <h2>Canonical contract</h2>
      <Rows pools={can} reg="canonical" />
      <h2>Demo contract</h2>
      <p className="small">Short claim periods; every path of the rule exercised on real Ethereum swaps (docs/SEEDS.md).</p>
      <Rows pools={demo} reg="demo" />
    </>
  );
}
