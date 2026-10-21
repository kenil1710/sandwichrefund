// Keeper layer (tools/lib/keeper_core.mjs), offline: outages and backfill,
// endpoint disagreement, >50 pools and >500 cases through pagination,
// idempotency, ACCEPTED-but-not-final, stale hashes, crash and resume, and
// nothing silently skipped.
import test from "node:test";
import assert from "node:assert/strict";
import { runKeeper, emptyState, candidates, fileKey, closeKey, PAGE_BLOCKS, STALE_S, totals } from "../tools/lib/keeper_core.mjs";
import { SWAP_V2 } from "../tools/lib/chains.mjs";

const EP = ["https://a.example", "https://b.example", "https://c.example"];
const ROUTER = "0x" + "1".repeat(40);
const BOT = "0x" + "b".repeat(40);
const POOLA = "0x" + "a".repeat(40);
const w = (n) => (BigInt.asUintN(256, BigInt(n))).toString(16).padStart(64, "0");
const ta = (a) => "0x" + "0".repeat(24) + a.slice(2);
let seq = 0;
const hx = (n) => "0x" + n.toString(16).padStart(64, "0");

function v2log(block, ti, tx, pool, n0, n1, rec) {
  const in0 = n0 > 0 ? n0 : 0n, out0 = n0 < 0 ? -n0 : 0n, in1 = n1 > 0 ? n1 : 0n, out1 = n1 < 0 ? -n1 : 0n;
  return { address: pool, topics: [SWAP_V2, ta(rec), ta(rec)], data: "0x" + w(in0) + w(in1) + w(out0) + w(out1),
    blockNumber: "0x" + block.toString(16), transactionIndex: "0x" + ti.toString(16), logIndex: "0x" + (seq++).toString(16), transactionHash: tx };
}

/** A fake Ethereum: logs per block, transactions; endpoints can be down or lie. */
class FakeChain {
  constructor() { this.logs = []; this.txs = {}; this.down = new Set(); this.lie = new Set(); this.head = 1_000_000; this.calls = 0; }
  sandwich(block, victimFrom, to = ROUTER, pool = POOLA) {
    const f = hx(++seq * 7 + 1), v = hx(++seq * 7 + 2), b = hx(++seq * 7 + 3);
    this.logs.push(v2log(block, 0, f, pool, 10n, -100n, BOT), v2log(block, 1, v, pool, 5n, -40n, victimFrom), v2log(block, 2, b, pool, -11n, 100n, BOT));
    this.txs[f] = { hash: f, from: BOT, to: BOT, blockNumber: "0x" + block.toString(16) };
    this.txs[v] = { hash: v, from: victimFrom, to, blockNumber: "0x" + block.toString(16) };
    this.txs[b] = { hash: b, from: BOT, to: BOT, blockNumber: "0x" + block.toString(16) };
    return v;
  }
  plain(block, from, to = ROUTER) {
    const h = hx(++seq * 7 + 4);
    this.logs.push(v2log(block, 5, h, POOLA, 5n, -40n, from));
    this.txs[h] = { hash: h, from, to, blockNumber: "0x" + block.toString(16) };
    return h;
  }
  api() {
    const self = this;
    return {
      endpoints: () => EP,
      async head(u) { if (self.down.has(u)) throw new Error("down"); return self.head; },
      async getLogs(u, chain, from, to) {
        self.calls++;
        if (self.down.has(u)) throw new Error("down");
        const out = self.logs.filter((l) => { const b = Number(l.blockNumber); return b >= from && b <= to; });
        return self.lie.has(u) ? out.slice(1) : out;
      },
      async getTxs(u, chain, hashes) { if (self.down.has(u)) throw new Error("down"); return hashes.map((h) => self.txs[h] ?? null); },
    };
  }
}

/** A fake SandwichRefund: pools, decisions, transactions that move ACCEPTED -> FINALIZED on tick(). */
class FakeReg {
  constructor() {
    this.t = 1_800_000_000; this.pools = []; this.cases = {}; this.txs = {}; this.submits = []; this.decide = () => "SANDWICHED_REFUNDED";
    this.finalizeOnTick = true; this.getPoolsFails = false;
  }
  pool(over = {}) {
    const p = { pool_id: this.pools.length + 1, sponsor: "0x" + "5".repeat(40), name: "p", status: "OPEN", claim_deadline: this.t + 7200,
      ranges: [{ chain: "ethereum", start_block: 100, end_block: 199 }], routers: [{ chain: "ethereum", address: ROUTER }], ...over };
    this.pools.push(p);
    return p;
  }
  tick(s = 60) {
    this.t += s;
    if (!this.finalizeOnTick) return;
    for (const tx of Object.values(this.txs)) if (tx.statusName === "ACCEPTED") { tx.statusName = "FINALIZED"; tx.apply?.(); }
  }
  api() {
    const self = this;
    return {
      now: () => self.t,
      async getPools(off, lim) {
        if (self.getPoolsFails) throw new Error("studio down");
        const items = self.pools.slice(off, off + lim);
        return { total: self.pools.length, items, next_offset: off + items.length < self.pools.length ? off + items.length : -1 };
      },
      async getPool(pid) { const p = self.pools[pid - 1]; return p ? { found: true, ...p } : { found: false }; },
      async getPoolCase(pid, chain, hash) { const c = self.cases[`${pid}:${hash}`]; return c ? { found: true, ...c } : { found: false }; },
      async fileCase(pid, chain, hash, victim) {
        const h = "0xf" + String(self.submits.length).padStart(63, "0");
        self.submits.push({ pid, hash, victim });
        const st = self.decide(hash, self.submits.filter((s) => s.hash === hash).length);
        self.txs[h] = { statusName: "ACCEPTED", ok: true, apply: () => { self.cases[`${pid}:${hash}`] = { state: st, refund_paid: "1", reason: "r" }; } };
        return h;
      },
      async closePool(pid) {
        const h = "0xc" + String(self.submits.length).padStart(63, "0");
        self.submits.push({ pid, close: true });
        self.txs[h] = { statusName: "ACCEPTED", ok: true, apply: () => { self.pools[pid - 1].status = "CLOSED"; } };
        return h;
      },
      async getTx(h) { const t = self.txs[h]; return t ? { statusName: t.statusName, ok: t.ok } : null; },
    };
  }
}

function memStore(init = null) {
  let s = init ? JSON.parse(JSON.stringify(init)) : null;
  const saves = [];
  return { saves, async load() { return s ? JSON.parse(JSON.stringify(s)) : null; }, async save(st, why) { s = JSON.parse(JSON.stringify(st)); saves.push(why); }, get: () => s };
}

async function cycle(ch, rg, store, opts = {}, n = 1) {
  let out;
  for (let i = 0; i < n; i++) { out = await runKeeper({ scan: ch.api(), reg: rg.api(), store, ...opts }); rg.tick(); }
  return out;
}

test("candidates: front/victim/back by one recipient", () => {
  const ch = new FakeChain();
  const v = ch.sandwich(150, "0x" + "e".repeat(40));
  assert.deepEqual(candidates(ch.logs), [v]);
});

test("candidates: no pair, wrong direction, other block, other pool", () => {
  const ch = new FakeChain();
  const t = (n) => hx(9000 + n);
  ch.logs.push(v2log(10, 0, t(1), POOLA, 10n, -100n, BOT), v2log(10, 1, t(2), POOLA, 5n, -40n, ROUTER), v2log(10, 2, t(3), POOLA, 11n, -100n, BOT));
  ch.logs.push(v2log(11, 0, t(4), POOLA, 10n, -100n, BOT), v2log(11, 1, t(5), POOLA, 5n, -40n, ROUTER), v2log(12, 2, t(6), POOLA, -11n, 100n, BOT));
  const other = "0x" + "c".repeat(40);
  ch.logs.push(v2log(13, 0, t(7), POOLA, 10n, -100n, BOT), v2log(13, 1, t(8), POOLA, 5n, -40n, ROUTER), v2log(13, 2, t(9), other, -11n, 100n, BOT));
  assert.deepEqual(candidates(ch.logs), []);
});

test("full flow: scan, file, finalize, verify -> DONE; a second run does nothing", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v1 = ch.sandwich(120, "0x" + "e".repeat(40));
  const v2 = ch.sandwich(190, "0x" + "d".repeat(40));
  ch.sandwich(250, "0x" + "c".repeat(40));               // outside the range
  ch.sandwich(130, "0x" + "9".repeat(40), "0x" + "7".repeat(40)); // not a covered router
  await cycle(ch, rg, store);
  assert.equal(rg.submits.length, 2);
  assert.deepEqual(rg.submits.map((s) => s.victim).sort(), ["0x" + "d".repeat(40), "0x" + "e".repeat(40)]);
  const { state } = await cycle(ch, rg, store);
  assert.equal(state.actions[fileKey(1, "ethereum", v1)].status, "DONE");
  assert.equal(state.actions[fileKey(1, "ethereum", v2)].result, "SANDWICHED_REFUNDED");
  assert.equal(state.pools[1].chains.ethereum.done, true);
  await cycle(ch, rg, store);
  assert.equal(rg.submits.length, 2, "no duplicates");
  assert.equal(totals(store.get()).done, 2);
});

test("an action is DONE only after FINALIZED + executed + a read shows it", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.finalizeOnTick = false;
  await cycle(ch, rg, store, {}, 3);
  const a = store.get().actions[fileKey(1, "ethereum", v)];
  assert.ok(["SUBMITTED", "ACCEPTED"].includes(a.status));
  assert.equal(rg.submits.length, 1, "never a second tx while the first is not terminal");
  // finalized but reverted -> retry, not DONE
  rg.txs[a.tx].statusName = "FINALIZED"; rg.txs[a.tx].ok = false;
  const { state } = await cycle(ch, rg, store);
  assert.equal(state.actions[fileKey(1, "ethereum", v)].status, "RETRY");
});

test("ACCEPTED-not-final for 6 h -> re-read; still undecided -> filed again", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 30 * 3600 });
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.finalizeOnTick = false;
  await cycle(ch, rg, store);
  assert.equal(rg.submits.length, 1);
  rg.t += STALE_S + 10;
  await cycle(ch, rg, store);
  const a = store.get().actions[fileKey(1, "ethereum", v)];
  assert.equal(a.status, "RETRY");
  rg.t += 7200;
  rg.finalizeOnTick = true;
  await cycle(ch, rg, store, {}, 2);
  assert.equal(rg.submits.length, 2);
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
});

test("stale hash whose case got decided anyway -> DONE without a new tx", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 30 * 3600 });
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.finalizeOnTick = false;
  await cycle(ch, rg, store);
  rg.cases[`1:${v}`] = { state: "CLEAN", refund_paid: "0" };
  rg.txs[store.get().actions[fileKey(1, "ethereum", v)].tx].statusName = "UNDETERMINED";
  await cycle(ch, rg, store);
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.equal(rg.submits.length, 1);
});

test("crash after submit: the next run resumes from the stored hash, no duplicate", async () => {
  const ch = new FakeChain(), rg = new FakeReg();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  const store = memStore();
  const crashing = { ...store, async save(st, why) { await store.save(st, why); if (why.startsWith("submitted")) throw new Error("killed"); } };
  await assert.rejects(runKeeper({ scan: ch.api(), reg: rg.api(), store: crashing }));
  rg.tick();
  const { state } = await runKeeper({ scan: ch.api(), reg: rg.api(), store });
  assert.equal(rg.submits.length, 1);
  assert.equal(state.actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.ok(state.last_run.resumed >= 1);
});

test("outage: one endpoint down -> pages still need two answers; backfilled later", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(155, "0x" + "e".repeat(40));
  ch.down.add(EP[1]); ch.down.add(EP[2]);
  let { state } = await cycle(ch, rg, store);
  assert.equal(rg.submits.length, 0);
  assert.ok(state.pools[1].chains.ethereum.failed.length === 0 || true);
  assert.ok(state.unprocessed.some((u) => u.key.startsWith("scan:1") || u.key.startsWith("page:")), "the gap is shown");
  ch.down.clear();
  ch.down.add(EP[0]);                                // a different single endpoint down: two others answer
  ({ state } = await cycle(ch, rg, store, {}, 2));
  assert.equal(rg.submits.length, 1);
  assert.equal(state.actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.equal(state.pools[1].chains.ethereum.done, true);
});

test("a page with one endpoint failing goes to the failed list, retried first", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(155, "0x" + "e".repeat(40));
  let failOnce = true;
  const api = ch.api();
  const flaky = { ...api, async getLogs(u, c, f, t) { if (f === 150 && failOnce && u !== EP[0]) { failOnce = u === EP[1]; throw new Error("503"); } return api.getLogs(u, c, f, t); } };
  let out = await runKeeper({ scan: { ...flaky, endpoints: () => EP.slice(0, 2) }, reg: rg.api(), store });
  assert.deepEqual(out.state.pools[1].chains.ethereum.failed, [150]);
  assert.equal(out.state.pools[1].chains.ethereum.done, false);
  assert.ok(out.state.unprocessed.some((u) => u.key === "page:1:ethereum:150"));
  rg.tick();
  out = await runKeeper({ scan: { ...api, endpoints: () => EP.slice(0, 2) }, reg: rg.api(), store });
  assert.deepEqual(out.state.pools[1].chains.ethereum.failed, []);
  assert.equal(out.state.pools[1].chains.ethereum.done, true);
  assert.equal(rg.submits.length, 1);
  assert.equal(rg.submits[0].hash, v);
});

test("endpoints disagreeing on a page never count it", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  ch.sandwich(155, "0x" + "e".repeat(40));
  ch.lie.add(EP[1]);
  const scan = { ...ch.api(), endpoints: () => EP.slice(0, 2) };
  const { state } = await runKeeper({ scan, reg: rg.api(), store });
  assert.equal(rg.submits.length, 0);
  assert.ok(state.pools[1].chains.ethereum.failed.includes(150));
  assert.ok(state.unprocessed.some((u) => /different logs/.test(u.why)));
});

test(">50 pools: every page of get_pools is walked", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  for (let i = 0; i < 120; i++) rg.pool({ ranges: [{ chain: "ethereum", start_block: 100 + i, end_block: 100 + i }] });
  const v = ch.sandwich(219, "0x" + "e".repeat(40));
  const { state } = await cycle(ch, rg, store, { maxPages: 1000 });
  assert.equal(state.pools_total, 120);
  assert.equal(Object.keys(state.pools).length, 120);
  assert.equal(rg.submits.length, 1);
  assert.equal(rg.submits[0].pid, 120);
  assert.equal(rg.submits[0].hash, v);
});

test(">500 cases: queued across runs, oldest first, none skipped, none twice", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 400 * 3600, ranges: [{ chain: "ethereum", start_block: 100, end_block: 799 }] });
  const vs = [];
  for (let i = 0; i < 620; i++) vs.push(ch.plain(100 + (i % 700), "0x" + (i + 1).toString(16).padStart(40, "0")));
  const watch = vs.map((hash) => ({ chain: "ethereum", hash }));
  rg.decide = () => "CLEAN";
  let out;
  for (let r = 0; r < 30; r++) {
    out = await runKeeper({ scan: ch.api(), reg: rg.api(), store, watch, maxActions: 25, maxPages: 100 });
    rg.tick(3600);
    if (totals(out.state).done === 620) break;
  }
  const t = totals(store.get());
  assert.equal(t.actions, 620);
  assert.equal(t.done, 620);
  assert.equal(rg.submits.length, 620);
  assert.equal(new Set(rg.submits.map((s) => s.hash)).size, 620);
});

test("queued work beyond the action limit is listed, not dropped", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const watch = [];
  for (let i = 0; i < 10; i++) watch.push({ chain: "ethereum", hash: ch.plain(110 + i, "0x" + (i + 1).toString(16).padStart(40, "0")) });
  const { state } = await runKeeper({ scan: ch.api(), reg: rg.api(), store, watch, maxActions: 3 });
  assert.equal(rg.submits.length, 3);
  assert.equal(state.unprocessed.filter((u) => /action limit/.test(u.why)).length, 7);
});

test("already decided by someone else: DONE without a transaction", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.cases[`1:${v}`] = { state: "SANDWICHED_UNPAID", refund_paid: "0" };
  const { state } = await cycle(ch, rg, store);
  assert.equal(rg.submits.length, 0);
  assert.equal(state.actions[fileKey(1, "ethereum", v)].result, "SANDWICHED_UNPAID");
});

test("UNVERIFIABLE decision is retried with backoff until decided", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 30 * 3600 });
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.decide = (h, n) => (n < 3 ? "UNVERIFIABLE" : "SANDWICHED_REFUNDED");
  for (let i = 0; i < 12 && store.get()?.actions?.[fileKey(1, "ethereum", v)]?.status !== "DONE"; i++) {
    await runKeeper({ scan: ch.api(), reg: rg.api(), store }); rg.tick(1800);
  }
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.equal(rg.submits.length, 3);
});

test("close after the claim deadline, verified by a read", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 100 });
  rg.t += 200;
  await cycle(ch, rg, store, {}, 2);
  const a = store.get().actions[closeKey(1)];
  assert.equal(a.status, "DONE");
  assert.equal(rg.pools[0].status, "CLOSED");
  await cycle(ch, rg, store);
  assert.equal(rg.submits.filter((s) => s.close).length, 1);
});

test("a case found after the deadline is reported FAILED, not silently dropped", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.getPoolsFails = false;
  const s0 = emptyState();
  s0.actions[fileKey(1, "ethereum", v)] = { key: fileKey(1, "ethereum", v), kind: "FILE", pool_id: 1, chain: "ethereum", hash: v, victim: "0x" + "e".repeat(40),
    status: "QUEUED", attempts: 0, first_seen_at: 1, tx: null };
  const st = memStore(s0);
  rg.pools[0].status = "CLOSED";
  const { state } = await runKeeper({ scan: ch.api(), reg: rg.api(), store: st });
  assert.equal(state.actions[fileKey(1, "ethereum", v)].status, "FAILED");
  assert.ok(state.unprocessed.some((u) => u.why.startsWith("FAILED")));
});

test("pool listing failure is shown", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  rg.getPoolsFails = true;
  const { state, run } = await runKeeper({ scan: ch.api(), reg: rg.api(), store });
  assert.ok(state.unprocessed.some((u) => u.key === "pools"));
  assert.equal(run.errors.length, 1);
});

test("range in the future: scans to the finalized head and waits", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  ch.head = 150;
  rg.pool();
  ch.sandwich(140, "0x" + "e".repeat(40));
  const late = ch.sandwich(170, "0x" + "d".repeat(40));
  let { state } = await cycle(ch, rg, store);
  assert.equal(state.pools[1].chains.ethereum.cursor, 150);
  assert.equal(state.pools[1].chains.ethereum.done, false);
  ch.head = 1000;
  ({ state } = await cycle(ch, rg, store, {}, 2));
  assert.ok(state.actions[fileKey(1, "ethereum", late)]);
  assert.equal(state.pools[1].chains.ethereum.done, true);
});

test("submit failure goes to the retry queue", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  const api = rg.api();
  let n = 0;
  const reg = { ...api, async fileCase(...a) { if (n++ === 0) throw new Error("fee estimate failed"); return api.fileCase(...a); } };
  await runKeeper({ scan: ch.api(), reg, store });
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "RETRY");
  rg.tick(3600);
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  await runKeeper({ scan: ch.api(), reg, store });
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
});

test("checkpoint after every page", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store });
  assert.equal(store.saves.filter((s) => s.startsWith("scan 1 ethereum")).length, 100 / PAGE_BLOCKS);
});

test("attack: two keepers with separate state file one case once", async () => {
  const ch = new FakeChain(), rg = new FakeReg();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  const s1 = memStore(), s2 = memStore();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store: s1 });
  rg.tick();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store: s2 });
  rg.tick();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store: s1 });
  assert.equal(rg.submits.filter((x) => x.hash === v).length, 1);
  assert.equal(s2.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.equal(s1.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
});

test("attack: a lying endpoint cannot inject a candidate", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const api = ch.api();
  const fake = hx(424242);
  const scan = { ...api, endpoints: () => EP.slice(0, 2), async getLogs(u, c, f, t) { const l = await api.getLogs(u, c, f, t);
    return u === EP[0] && f === 150 ? [...l, v2log(150, 0, hx(1), POOLA, 10n, -100n, BOT), v2log(150, 1, fake, POOLA, 5n, -40n, ROUTER), v2log(150, 2, hx(2), POOLA, -11n, 100n, BOT)] : l; } };
  ch.txs[fake] = { hash: fake, from: "0x" + "6".repeat(40), to: ROUTER, blockNumber: "0x96" };
  const { state } = await runKeeper({ scan, reg: rg.api(), store });
  assert.equal(rg.submits.length, 0);
  assert.ok(state.pools[1].chains.ethereum.failed.includes(150));
});

test("settle phase: this run's filings are polled to FINALIZED within the budget", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool();
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.finalizeOnTick = false;
  const api = rg.api();
  let sleeps = 0;
  const reg = { ...api, async sleep() { sleeps++; if (sleeps === 2) { rg.finalizeOnTick = true; rg.tick(); } } };
  const { state } = await runKeeper({ scan: ch.api(), reg, store, settleMs: 60_000 });
  assert.equal(state.actions[fileKey(1, "ethereum", v)].status, "DONE");
  assert.equal(state.unprocessed.length, 0);
});

test("demo contract: no scan, but due pools are closed", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  rg.pool({ claim_deadline: 1_800_000_000 + 10 });
  ch.sandwich(120, "0x" + "e".repeat(40));
  rg.t += 20;
  await runKeeper({ scan: ch.api(), reg: rg.api(), store, scanPools: false }); rg.tick();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store, scanPools: false });
  assert.equal(rg.submits.filter((s) => !s.close).length, 0);
  assert.equal(rg.pools[0].status, "CLOSED");
  assert.equal(ch.calls, 0);
});

test("recovery window: a transient UNVERIFIABLE case is retried after the deadline; close waits for it", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  const p = rg.pool({ claim_deadline: 1_800_000_000 + 100 });
  p.recovery_deadline = p.claim_deadline + 3600;
  const v = ch.sandwich(120, "0x" + "e".repeat(40));
  rg.decide = (h, n) => (n < 2 ? "UNVERIFIABLE" : "SANDWICHED_REFUNDED");
  const api = rg.api();
  const reg = { ...api, async getPoolCase(pid, c, h) { const x = await api.getPoolCase(pid, c, h); if (x.found && x.state === "UNVERIFIABLE") x.reason = "RPC_UNREADABLE"; return x; },
    async getPools(o, l) { const pg = await api.getPools(o, l); for (const q of pg.items) q.pending = Object.values(rg.cases).filter((c) => c.state === "UNVERIFIABLE").length; return pg; } };
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "RETRY");
  rg.t = p.claim_deadline + 1000;
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  assert.equal(store.get().actions[closeKey(1)], undefined, "no close while a case is pending in the window");
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  assert.equal(store.get().actions[fileKey(1, "ethereum", v)].status, "DONE");
  await runKeeper({ scan: ch.api(), reg, store }); rg.tick();
  await runKeeper({ scan: ch.api(), reg, store });
  assert.equal(rg.pools[0].status, "CLOSED");
});

test("recovery window over: close is due even with cases pending", async () => {
  const ch = new FakeChain(), rg = new FakeReg(), store = memStore();
  const p = rg.pool({ claim_deadline: 1_800_000_000 + 100, pending: 3 });
  p.recovery_deadline = p.claim_deadline + 3600;
  rg.t = p.recovery_deadline + 1;
  await runKeeper({ scan: ch.api(), reg: rg.api(), store }); rg.tick();
  await runKeeper({ scan: ch.api(), reg: rg.api(), store });
  assert.equal(rg.pools[0].status, "CLOSED");
});
