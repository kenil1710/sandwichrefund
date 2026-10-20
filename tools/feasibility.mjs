// Step 0: every case in data/cases.json read from both RPCs of its chain
// (tools/lib/chains.mjs) from this machine, judged against the canonical
// pool's terms (data/pool_canonical.json) -> docs/feasibility.json.
//   node tools/feasibility.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { readBoth, judge } from "./lib/sandwich.mjs";
import { CHAINS } from "./lib/chains.mjs";
import { chainTerms } from "./lib/terms.mjs";

const root = new URL("../", import.meta.url);
const data = JSON.parse(readFileSync(new URL("data/cases.json", root)));
const pool = JSON.parse(readFileSync(new URL("data/pool_canonical.json", root)));
const out = { generated_at: new Date().toISOString(), rpcs: CHAINS, range: pool.ranges, cases: [] };
for (const c of data.cases) {
  const r = await readBoth(c.chain, c.hash);
  const j = judge(chainTerms(pool, c.chain), r);
  const f = r.facts;
  out.cases.push({ chain: c.chain, hash: c.hash, expect: c.expect, verdict: j.verdict, reason: j.reason, agree: !r.reason,
    rpc_detail: r.detail ?? "", swaps_in_block: f ? f.swaps.filter((s) => s.block === f.tx.block).length : 0,
    pools: f ? f.pools : [], ...j, facts: f ?? null });
  console.log(c.hash.slice(0, 12), j.verdict.padEnd(12), j.reason.padEnd(26), c.expect === j.verdict ? "" : "EXPECTED " + c.expect);
}
writeFileSync(new URL("docs/feasibility.json", root), JSON.stringify(out, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1) + "\n");
const n = (v) => out.cases.filter((x) => x.verdict === v).length;
console.log(`cases ${out.cases.length}  SANDWICHED ${n("SANDWICHED")}  CLEAN ${n("CLEAN")}  UNCLEAR ${n("UNCLEAR")}  other ${out.cases.length - n("SANDWICHED") - n("CLEAN") - n("UNCLEAR")}`);
