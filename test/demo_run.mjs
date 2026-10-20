/**
 * The demo run on SandwichRefundDemo + MEVGateDemo: every path of the rule
 * and every payout, on real Ethereum swaps (docs/FEASIBILITY.md), each payout
 * proved by its arrival (balance delta at the recipient, the transaction
 * FINALIZED and its value message delivered), and the contract's own balance
 * back to 0 at the end. Writes docs/demo-run.json; resumable (finished steps
 * are kept).
 *   node demo_run.mjs
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { client, deployments, balanceOf, finalized, payoutDelivered, plain, gen } from "../tools/lib/sr.mjs";

const OUT = new URL("../docs/demo-run.json", import.meta.url);
const dep = deployments().contracts;
const ADDR = dep.SandwichRefundDemo.address, GATE = dep.MEVGateDemo.address;
const canon = JSON.parse(readFileSync(new URL("../data/pool_canonical.json", import.meta.url)));
const feas = JSON.parse(readFileSync(new URL("../docs/feasibility.json", import.meta.url)));
const byPrefix = (p) => { const c = feas.cases.find((x) => x.hash.startsWith(p)); if (!c) throw new Error("no case " + p); return c; };
const doc = existsSync(OUT) ? JSON.parse(readFileSync(OUT)) : { contract: ADDR, gate: GATE, steps: [], pools: {} };
const save = () => writeFileSync(OUT, JSON.stringify(doc, null, 1) + "\n");
const sp = client({ role: "sponsor", address: ADDR });
const sp2 = client({ role: "sponsor2", address: ADDR });
const fl = client({ role: "filer", address: ADDR });
const st = client({ role: "stranger", address: ADDR });
const gate = client({ role: "filer", address: GATE });
const GEN = 10n ** 18n;
const done = (id) => doc.steps.find((s) => s.id === id && s.ok);

async function step(id, what, fn) {
  if (done(id)) { console.log("skip", id); return done(id); }
  console.log("\n==", id, what);
  const r = await fn();
  const rec = { id, what, ...r, at: new Date().toISOString() };
  doc.steps = doc.steps.filter((s) => s.id !== id);
  doc.steps.push(rec);
  save();
  console.log("  ->", rec.ok ? "ok" : "FAIL", JSON.stringify({ ...rec, what: undefined }).slice(0, 400));
  if (!rec.ok) throw new Error("step failed: " + id);
  return rec;
}

/** A write whose effect (and payout, if any) is verified: finalized, delivered, balance delta at the recipient. */
async function paying(c, fn, args, payee, amountOf) {
  const before = payee ? await balanceOf(payee) : 0n;
  const cbefore = await balanceOf(ADDR);
  const w = await c.write(fn, args, { payee, simulate: false });
  if (!w.ok) return { ok: false, tx: w.hash, status: w.status, reason: w.reason };
  const tx = await finalized(c.read, w.hash);
  const ret = w.returned && typeof w.returned === "object" ? w.returned : null;
  const amount = BigInt(amountOf(ret) ?? "0");
  const out = { ok: tx?.statusName === "FINALIZED", tx: w.hash, status: tx?.statusName, returned: ret };
  if (amount > 0n) {
    const d = payoutDelivered(tx, payee, amount);
    let after = await balanceOf(payee);
    for (let i = 0; i < 6 && after - before < amount; i++) { await new Promise((r) => setTimeout(r, 10000)); after = await balanceOf(payee); }
    const cafter = await balanceOf(ADDR);
    // a payee that sent the transaction itself also paid its fee
    const sender = c.me.toLowerCase() === payee.toLowerCase();
    out.payout = { to: payee, amount: String(amount), delivered: d.ok, why: d.why, recipient_delta: String(after - before),
      contract_delta: String(cafter - cbefore), arrived: sender ? after - before === amount - BigInt(d.netFee ?? 0) : after - before === amount };
    out.ok = out.ok && d.ok && out.payout.arrived && cafter - cbefore === -amount;
  }
  return out;
}

const fileCase = (pool, c, expect) => paying(fl, "file_case", [pool, "ethereum", c.hash], c.victim, (r) => r?.refund).then(async (r) => {
  const pc = await fl.view("get_pool_case", [pool, "ethereum", c.hash]);
  r.case = { state: pc.state, reason: pc.reason, limit: pc.limit, loss: pc.loss, refund_due: pc.refund_due, refund_paid: pc.refund_paid, victim: pc.victim };
  r.expect = expect;
  r.ok = r.ok && pc.state === expect.state && (!expect.reason || pc.reason === expect.reason) && (!expect.limit || pc.limit === expect.limit);
  return r;
});

const rates = (num) => JSON.stringify([{ chain: "ethereum", token: "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", num: String(num), den: "1", symbol: "WETH", decimals: 18 }]);
const routersExcept = (a) => JSON.stringify(canon.routers.filter((r) => r.address !== a));
const V2_ROUTER = "0x7a250d5630b4cf539739df2c5dacb4c659f2488d";

async function createPool(key, who, name, args, value) {
  return step("create_" + key, "create pool " + name, async () => {
    const n0 = (await who.view("get_stats")).pools;
    const w = await who.write("create_pool", [name, ...args], { value });
    const tx = w.hash ? await finalized(who.read, w.hash) : null;
    const pid = w.returned?.pool_id ?? (await who.view("get_stats")).pools;
    doc.pools[key] = pid;
    const p = await who.view("get_pool", [pid, 0]);
    return { ok: w.ok && tx?.statusName === "FINALIZED" && w.returned?.ok === true && pid === n0 + 1, tx: w.hash, pool_id: pid, claim_deadline: p.claim_deadline, funded: p.funded };
  });
}

// ---------------------------------------------------------------------------
// 0. a refused pool: the GEN is credited, then withdrawn (a payout to the sponsor)
await step("refused_create", "create_pool with a bad claim period is refused and credited", async () => {
  const w = await sp.write("create_pool", ["bad", '["ethereum"]', routersExcept(""), '["V2"]', JSON.stringify(canon.ranges), rates(100), String(GEN / 20), String(GEN / 10), 5, "{}"], { value: GEN / 100 });
  const credit = await sp.view("get_credit", [sp.me]);
  return { ok: w.ok && w.returned?.ok === false && w.returned?.reason === "BAD_CLAIM_PERIOD" && credit.credit === String(GEN / 100), tx: w.hash, returned: w.returned, credit: credit.credit };
});
await step("withdraw_refund", "withdraw_refund pays the credit back", () => paying(sp, "withdraw_refund", [], sp.me, (r) => r?.withdrawn));

// 1. pool A: every refund limit, pool empty, unpriced token, uncovered router, clean, unclear, unverifiable
await createPool("A", sp, "Demo A: caps, empty pool, every verdict", ['["ethereum"]', routersExcept(V2_ROUTER), '["V2","V3"]', JSON.stringify(canon.ranges), rates(100),
  String(GEN / 20), String(GEN / 10), 1500, '{"demo":"A"}'], (33n * GEN) / 100n);
const A = doc.pools.A;
const B3 = (p) => byPrefix(p);
await step("A_max_per_swap", "a sandwich due 0.0786 GEN, capped at max per swap 0.05", () => fileCase(A, B3("0x3ecd364f"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_SWAP" }));
await step("A_rate", "the same victim's second sandwich, paid at the rate (0.0341)", () => fileCase(A, B3("0x7d38614e"), { state: "SANDWICHED_REFUNDED", limit: "RATE" }));
await step("A_max_per_victim", "the same victim's third sandwich: only what is left of its 0.1 cap", () => fileCase(A, B3("0x78b3b263"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_VICTIM" }));
await step("A_cap_big", "a 0.09 WETH sandwich (due 9 GEN), capped at 0.05", () => fileCase(A, byPrefix("0x29960a40"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_SWAP" }));
await step("A_cap_2", "another capped refund", () => fileCase(A, byPrefix("0x643387b0"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_SWAP" }));
await step("A_cap_3", "another capped refund", () => fileCase(A, byPrefix("0xc3a58de6"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_SWAP" }));
await step("A_cap_4", "another capped refund", () => fileCase(A, byPrefix("0xa3bacdd6"), { state: "SANDWICHED_REFUNDED", limit: "MAX_PER_SWAP" }));
await step("A_pool_balance", "the pool's last GEN: a partial refund", () => fileCase(A, byPrefix("0x3cb99a76"), { state: "SANDWICHED_REFUNDED", limit: "POOL_BALANCE" }));
await step("A_unpaid", "pool empty: SANDWICHED_UNPAID", () => fileCase(A, byPrefix("0xb497f700"), { state: "SANDWICHED_UNPAID", limit: "POOL_BALANCE" }));
await step("A_unpriced", "a sandwich with USDT profit, unpriced in this pool", () => fileCase(A, byPrefix("0xa3810601"), { state: "UNCLEAR", reason: "PROFIT_TOKEN_NOT_PRICED" }));
await step("A_not_covered", "a sandwich through Uniswap V2 Router02, not covered by this pool", () => fileCase(A, byPrefix("0x4275a602"), { state: "NOT_COVERED", reason: "ROUTER_NOT_COVERED" }));
const clean = feas.cases.find((c) => c.verdict === "CLEAN" && c.router !== V2_ROUTER);
await step("A_clean", "a clean swap", () => fileCase(A, clean, { state: "CLEAN", reason: "NO_PATTERN" }));
const multi = feas.cases.find((c) => c.reason === "MULTI_HOP_VICTIM" && c.router !== V2_ROUTER);
await step("A_unclear", "a sandwiched multi-hop swap", () => fileCase(A, multi, { state: "UNCLEAR", reason: "MULTI_HOP_VICTIM" }));
const bundle = feas.cases.find((c) => c.reason === "MULTIPLE_VICTIMS" && c.router !== V2_ROUTER);
if (bundle) await step("A_bundle", "one victim of a bundle with several", () => fileCase(A, bundle, { state: "UNCLEAR", reason: "MULTIPLE_VICTIMS" }));
const FAKE = "0x" + "5a".repeat(32);
await step("A_unverifiable", "a hash Ethereum does not know", () => fileCase(A, { hash: FAKE, victim: null }, { state: "UNVERIFIABLE", reason: "TX_NOT_FOUND" }));
await step("A_refile_unverifiable", "UNVERIFIABLE can be filed again", async () => {
  const r = await fileCase(A, { hash: FAKE, victim: null }, { state: "UNVERIFIABLE", reason: "TX_NOT_FOUND" });
  const pc = await fl.view("get_pool_case", [A, "ethereum", FAKE]);
  return { ...r, attempts: pc.attempts, ok: r.ok && pc.attempts === 2 };
});
await step("A_duplicate", "a decided case filed again is refused", async () => {
  const w = await st.write("file_case", [A, "ethereum", byPrefix("0x3ecd364f").hash], { payee: byPrefix("0x3ecd364f").victim, simulate: false });
  return { ok: !w.ok && /ALREADY_DECIDED_SANDWICHED_REFUNDED/.test(w.reason ?? ""), tx: w.hash, status: w.status, reason: w.reason };
});
await step("A_top_up", "anyone tops the pool up (sponsor2, 0.02 GEN)", async () => {
  const w = await sp2.write("top_up", [A], { value: GEN / 50 });
  const tx = w.hash ? await finalized(sp2.read, w.hash) : null;
  const p = await sp2.view("get_pool", [A, 0]);
  return { ok: w.ok && tx?.statusName === "FINALIZED" && p.balance === String(GEN / 50), tx: w.hash, balance: p.balance };
});
await step("A_extend_stranger", "a stranger cannot extend", async () => {
  const p = await st.view("get_pool", [A, 0]);
  const w = await st.write("extend", [A, p.claim_deadline + 60]);
  return { ok: !w.ok && /ONLY_THE_SPONSOR/.test(w.reason ?? ""), tx: w.hash, reason: w.reason };
});
await step("A_extend", "the sponsor extends by 60 s", async () => {
  const p = await sp.view("get_pool", [A, 0]);
  const w = await sp.write("extend", [A, p.claim_deadline + 60]);
  const q = await sp.view("get_pool", [A, 0]);
  return { ok: w.ok && q.claim_deadline === p.claim_deadline + 60, tx: w.hash, from: p.claim_deadline, to: q.claim_deadline };
});
await step("A_close_early", "closing before the claim deadline is refused", async () => {
  const w = await st.write("close_pool", [A], { payee: sp.me, simulate: false });
  return { ok: !w.ok && /CLAIM_PERIOD_OPEN_UNTIL/.test(w.reason ?? ""), tx: w.hash, reason: w.reason };
});

// 2. pool B: a block range and a pool type that leave cases out
await createPool("B", sp, "Demo B: blocks 26231000-26231420, V2 only", ['["ethereum"]', routersExcept(""), '["V2"]',
  JSON.stringify([{ chain: "ethereum", start_block: 26231000, end_block: 26231420 }]), rates(100), String(GEN / 20), String(GEN / 10), 120, '{"demo":"B"}'], GEN / 100);
const B = doc.pools.B;
await step("B_outside_range", "a sandwich before the pool's block range", () => fileCase(B, byPrefix("0xa3bacdd6"), { state: "NOT_COVERED", reason: "OUTSIDE_BLOCK_RANGE" }));
await step("B_kind", "a V3 sandwich in range, but the pool covers V2 only", () => fileCase(B, byPrefix("0xc3a58de6"), { state: "NOT_COVERED", reason: "POOL_TYPE_NOT_COVERED" }));
await step("B_refunded", "a V2 sandwich in range, refunded at pool B's rate", () => fileCase(B, byPrefix("0x1b17869b"), { state: "SANDWICHED_REFUNDED", limit: "RATE" }));

// 3. MEVGateDemo
await step("gate", "MEVGateDemo reads every state", async () => {
  const q = async (h, ch = "ethereum") => (await gate.view("check_case", [ch, h]));
  const got = {
    refunded: await q(byPrefix("0x3ecd364f").hash), unpaid: await q(byPrefix("0xb497f700").hash), clean: await q(clean.hash),
    unclear: await q(multi.hash), not_covered: await q(byPrefix("0x4275a602").hash), unverifiable: await q(FAKE),
    unfiled: await q("0x" + "77".repeat(32)), no_pool: await q(byPrefix("0x3ecd364f").hash, "base"),
  };
  const addr = await gate.view("check_address", [byPrefix("0x3ecd364f").victim]);
  const want = { refunded: "SANDWICHED_REFUNDED", unpaid: "SANDWICHED_UNPAID", clean: "CLEAN", unclear: "UNCLEAR", not_covered: "NOT_COVERED",
    unverifiable: "UNVERIFIABLE", unfiled: "UNVERIFIABLE", no_pool: "NO_POOL" };
  const ok = Object.entries(want).every(([k, v]) => got[k].state === v) && got.clean.clean === true && got.refunded.refunded === true
    && Object.values(got).filter((g) => g.clean).length === 1 && addr.state === "SANDWICHED_REFUNDED" && addr.cases === 3;
  return { ok, states: Object.fromEntries(Object.entries(got).map(([k, g]) => [k, { state: g.state, clean: g.clean, refunded: g.refunded, why: g.why }])), address: addr };
});
await step("gate_attest", "attest_case stores a reading on chain", async () => {
  const w = await gate.write("attest_case", ["ethereum", byPrefix("0x3ecd364f").hash]);
  const a = await gate.view("latest_attestation", ["ethereum", byPrefix("0x3ecd364f").hash]);
  return { ok: w.ok && a.found && a.state === "SANDWICHED_REFUNDED", tx: w.hash, attestation_id: a.attestation_id };
});

// 4. close both pools after their deadlines: the rest goes back to the sponsor
async function waitDeadline(pid) {
  for (;;) {
    const p = await sp.view("get_pool", [pid, Math.floor(Date.now() / 1000)]);
    const left = p.claim_deadline - Math.floor(Date.now() / 1000);
    if (left < -15) return p;
    console.log(`  waiting ${left + 20}s for pool ${pid}'s claim deadline`);
    await new Promise((r) => setTimeout(r, Math.min(Math.max(left + 20, 5), 120) * 1000));
  }
}
for (const key of ["B", "A"]) {
  const pid = doc.pools[key];
  await step("close_" + key, `close pool ${key} after its deadline: the rest to the sponsor`, async () => {
    const p = await waitDeadline(pid);
    if (p.status === "CLOSED") return { ok: true, already: true, returned: p.returned };
    const r = await paying(st, "close_pool", [pid], p.sponsor, (x) => x?.returned);
    const q = await st.view("get_pool", [pid, 0]);
    return { ...r, ok: r.ok && q.status === "CLOSED" && BigInt(q.refunded) + BigInt(q.returned) === BigInt(q.funded), pool: { funded: q.funded, refunded: q.refunded, returned: q.returned } };
  });
}

await step("final_balance", "the demo contract holds nothing: eth_getBalance 0", async () => {
  const b = await balanceOf(ADDR);
  const s = await sp.view("get_stats");
  return { ok: b === 0n && s.held === "0", balance: String(b), stats: s };
});
console.log("\ndemo run complete:", doc.steps.length, "steps");
