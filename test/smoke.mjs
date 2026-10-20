// Smoke on the smoke set (deployments.smoke.json): create a DEMO pool, file one
// real sandwiched swap, check the refund ARRIVED at the victim (balance delta),
// then a CLEAN one, then close the pool and check the sponsor got the rest.
//   node smoke.mjs
import { readFileSync } from "node:fs";
import { client, deployments, balanceOf, finalized, payoutDelivered, gen, plain } from "../tools/lib/sr.mjs";

const dep = deployments("smoke").contracts;
const addr = dep.SandwichRefundDemo.address;
const pool = JSON.parse(readFileSync(new URL("../data/pool_canonical.json", import.meta.url)));
const feas = JSON.parse(readFileSync(new URL("../docs/feasibility.json", import.meta.url)));
const sand = feas.cases.find((c) => c.verdict === "SANDWICHED");
const clean = feas.cases.find((c) => c.verdict === "CLEAN");
const sp = client({ role: "sponsor", address: addr });
const kp = client({ role: "keeper", address: addr });
const step = (n, r) => console.log(n.padEnd(14), r.ok ? "ok" : "FAIL", r.status, r.hash, r.reason?.slice(0, 160) ?? "", JSON.stringify(r.returned ?? "").slice(0, 300));

const cr = await sp.write("create_pool", ["smoke", JSON.stringify(pool.chains), JSON.stringify(pool.routers), JSON.stringify(pool.kinds),
  JSON.stringify(pool.ranges), JSON.stringify(pool.rates), pool.max_per_swap, pool.max_per_victim, 120, "{}"], { value: 10n ** 17n });
step("create_pool", cr);
const stats = await sp.view("get_stats");
const pid = stats.pools;
console.log("pool", pid, "balance", stats.balance);
const before = await balanceOf(sand.victim);
const fr = await kp.write("file_case", [pid, "ethereum", sand.hash], { payee: sand.victim, simulate: false });
step("file_case", fr);
const c = await kp.view("get_pool_case", [pid, "ethereum", sand.hash]);
console.log("case", c.state, c.reason, "refund", c.refund_paid, "limit", c.limit, "victim", c.victim);
if (fr.hash) {
  const tx = await finalized(kp.read, fr.hash);
  console.log("finalized", tx?.statusName, JSON.stringify(plain(payoutDelivered(tx, sand.victim, c.refund_paid))));
}
const after = await balanceOf(sand.victim);
console.log("victim balance delta", gen(after - before), "GEN (expected", gen(BigInt(c.refund_paid)) + ")");
const fc = await kp.write("file_case", [pid, "ethereum", clean.hash], { payee: clean.victim, simulate: false });
step("file clean", fc);
console.log("clean case", (await kp.view("get_pool_case", [pid, "ethereum", clean.hash])).state);
