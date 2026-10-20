/**
 * Seeds the canonical pool on SandwichRefund (CANONICAL): the real routers of
 * docs/FEASIBILITY.md, the real block range, a small symbolic GEN pool, a 1 h
 * claim period. Records every victim's Studio Dev balance first, so a refund
 * can later be proved by its arrival (balance delta at the recipient).
 * The keeper (tools/keeper.mjs) then files every case; test/seed_verify.mjs checks.
 *   node seed_canonical.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { client, deployments, balanceOf, finalized } from "../tools/lib/sr.mjs";

const out = new URL("../docs/seed-canonical.json", import.meta.url);
if (existsSync(out) && JSON.parse(readFileSync(out)).pool_id) { console.log("already seeded", JSON.parse(readFileSync(out)).pool_id); process.exit(0); }
const dep = deployments().contracts;
const addr = dep.SandwichRefund.address;
const pool = JSON.parse(readFileSync(new URL("../data/pool_canonical.json", import.meta.url)));
const feas = JSON.parse(readFileSync(new URL("../docs/feasibility.json", import.meta.url)));
const victims = [...new Set(feas.cases.map((c) => c.victim).filter(Boolean))];
const baseline = {};
for (const v of victims) baseline[v] = String(await balanceOf(v));
console.log("baseline balances for", victims.length, "victims");
const sp = client({ role: "sponsor", address: addr });
const sponsorBefore = String(await balanceOf(sp.me));
const r = await sp.write("create_pool", [pool.name, JSON.stringify(pool.chains), JSON.stringify(pool.routers), JSON.stringify(pool.kinds),
  JSON.stringify(pool.ranges), JSON.stringify(pool.rates), pool.max_per_swap, pool.max_per_victim, pool.claim_period_s,
  JSON.stringify(pool.meta)], { value: BigInt(pool.value) });
console.log("create_pool", r.ok, r.status, r.hash, r.reason);
if (!r.ok) process.exit(1);
const st = await sp.view("get_stats");
const p = await sp.view("get_pool", [st.pools, 0]);
const tx = await finalized(sp.read, r.hash);
writeFileSync(out, JSON.stringify({ contract: addr, pool_id: p.pool_id, create_tx: r.hash, create_status: tx?.statusName, sponsor: sp.me,
  sponsor_balance_before: sponsorBefore, value: pool.value, claim_deadline: p.claim_deadline, created_at: p.created_at,
  victims_baseline: baseline, at: new Date().toISOString() }, null, 1) + "\n");
console.log("pool", p.pool_id, "claim deadline", new Date(p.claim_deadline * 1000).toISOString(), tx?.statusName);
