// The keeper's logic, with the chains, the contract and the state store
// injected so the offline tests (test/keeper.test.mjs) drive it through
// outages, crashes, half-final transactions and hundreds of pools and cases.
//
// One run:
//   1. RESUME every action with a stored transaction hash that is not finished:
//      poll that hash. Never submit a second transaction for an action whose
//      last one is not terminal - unless it has had no final status for 6 h,
//      then the case is re-read and, if still undecided, filed again.
//   2. POOLS: walk every page of get_pools from the persisted offset.
//   3. SCAN each open pool's block range on each of its chains from its
//      persisted cursor, page by page (PAGE_BLOCKS blocks). A page counts only
//      when two scan endpoints answered it with the same logs; otherwise it is
//      kept in the pool's failed-page list and retried first next run (the
//      cursor still advances, so one bad page never blocks the rest). Every
//      candidate victim (a swap with a same-pool, same-actor opposite pair
//      around it) whose transaction went to a covered router - its `to` read
//      from two endpoints - becomes a FILE action. So does every watchlist
//      hash (data/cases.json) inside the range.
//   5. SETTLE: poll this run's transactions until FINALIZED, within settleMs.
//   4. ACT, oldest first, up to maxActions (a case left UNVERIFIABLE for a
//      transient reason is retried in the pool's recovery window too; a pool is
//      closed once closable: past its deadline with nothing pending, or past
//      its recovery window): re-read the pool's decision on the
//      case (already decided -> DONE, no transaction), else file it and
//      checkpoint the hash at once. Pools past their claim deadline get a
//      CLOSE action.
// An action is DONE only when its transaction is FINALIZED, executed
// successfully, and a read shows the effect (the case decided, the pool
// closed). An UNVERIFIABLE decision is retried with backoff. Everything not
// finished this run is listed in state.unprocessed with the reason.
import { SWAP_V2, SWAP_V3 } from "./chains.mjs";
import { decodeSwap } from "./sandwich.mjs";

export const VERSION = 1;
export const MAX_ATTEMPTS = 8;
export const POOL_PAGE = 50;
export const PAGE_BLOCKS = 10;
export const STALE_S = 6 * 3600;
const TERMINAL_BAD = ["UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"];
const DONE_STATES = ["CLEAN", "SANDWICHED_REFUNDED", "SANDWICHED_UNPAID", "UNCLEAR", "NOT_COVERED", "EXPIRED"];
// UNVERIFIABLE for these reasons may be filed again in the pool's recovery window after its claim deadline
export const TRANSIENT = ["RPC_UNREADABLE", "RPC_DISAGREE", "NOT_FINALIZED", "TX_PENDING"];
/** May anyone close the pool now? Past the deadline, and no case pending or the recovery window over. */
export const closable = (p, now) => p.status === "OPEN" && now > p.claim_deadline && (!(p.pending > 0) || now > (p.recovery_deadline ?? p.claim_deadline));

export function emptyState() {
  return { version: VERSION, pools_offset: 0, pools: {}, actions: {}, runs: [], unprocessed: [], last_run: null };
}

export const fileKey = (pid, chain, hash) => `file:${pid}:${chain}:${hash.toLowerCase()}`;
export const closeKey = (pid) => `close:${pid}`;
export const backoffS = (attempts) => Math.min(60 * 2 ** Math.max(attempts - 1, 0), 6 * 3600);

const dir = (s) => { const a = BigInt(s.n0), b = BigInt(s.n1); return a > 0n && b < 0n ? 0 : b > 0n && a < 0n ? 1 : -1; };

/** Candidate victims in one page of Swap logs: a swap with a same-pool front
 *  (same direction, earlier) and back (opposite, later) by one actor (same
 *  Swap recipient) around it, in one block. The contract decides; this only
 *  picks what to file. -> [tx hash] */
export function candidates(logs) {
  const by = {};
  for (const l of logs) {
    const s = decodeSwap(l);
    if (!s) continue;
    (by[s.block + "|" + s.pool] ??= []).push(s);
  }
  const out = new Set();
  for (const arr of Object.values(by)) {
    if (arr.length < 3) continue;
    for (const v of arr) {
      const d = dir(v);
      if (d < 0) continue;
      const fr = arr.filter((s) => s.ti < v.ti && dir(s) === d && s.tx !== v.tx && s.recipient !== v.recipient);
      if (!fr.length) continue;
      const bk = arr.filter((s) => s.ti > v.ti && dir(s) === 1 - d && s.tx !== v.tx);
      if (fr.some((f) => bk.some((b) => b.recipient === f.recipient))) out.add(v.tx);
    }
  }
  return [...out].sort();
}

const logKey = (l) => `${String(l.transactionHash).toLowerCase()}:${Number(l.logIndex)}:${String(l.data).toLowerCase()}`;

/**
 * scan:  { endpoints(chain) -> [url], getLogs(url, chain, from, to) -> [log], getTxs(url, chain, [hash]) -> [{hash, from, to, blockNumber} | null],
 *          head(url, chain) -> finalized block number }
 * reg:   { now(), getPools(offset, limit) -> page, getPoolCase(pid, chain, hash) -> case,
 *          getPool(pid) -> pool, fileCase(pid, chain, hash, victim) -> hash, closePool(pid, sponsor) -> hash,
 *          getTx(hash) -> {statusName, ok, reason} | null }
 * store: { load() -> state, save(state, why) }
 * watch: [{chain, hash}]   hashes to file whatever the scan finds
 */
export async function runKeeper({ scan, reg, store, watch = [], log = () => {}, maxActions = 25, maxPages = 400, waitMs = 0, settleMs = 0, scanPools = true }) {
  const state = (await store.load()) ?? emptyState();
  const now0 = reg.now();
  const run = { started_at: now0, finished_at: null, resumed: 0, pools: 0, pages: 0, pages_failed: 0, candidates: 0,
    submitted: 0, done: 0, already: 0, pending: 0, failed: 0, retry: 0, errors: [] };
  const unprocessed = new Map();
  const note = (key, why) => unprocessed.set(key, { key, why });
  const save = async (why) => { await store.save(state, why); };

  function addFile(pid, chain, hash, victim, why) {
    const k = fileKey(pid, chain, hash);
    if (state.actions[k]) return false;
    state.actions[k] = { key: k, kind: "FILE", pool_id: pid, chain, hash: hash.toLowerCase(), victim, why, status: "QUEUED",
      attempts: 0, first_seen_at: reg.now(), tx: null };
    run.candidates++;
    return true;
  }

  async function verify(a) {
    if (a.kind === "FILE") {
      const c = await reg.getPoolCase(a.pool_id, a.chain, a.hash);
      return c?.found ? c : null;
    }
    const p = await reg.getPool(a.pool_id);
    return p?.found && p.status === "CLOSED" ? p : null;
  }

  async function conclude(a, tx) {
    const now = reg.now();
    let seen = null;
    try { seen = await verify(a); } catch (e) {
      a.last_error = "verifying read failed: " + String(e.message).slice(0, 120);
      run.pending++; note(a.key, `${a.tx} ${tx?.statusName ?? "?"}; verifying read failed, checked next run`);
      return;
    }
    const decided = a.kind === "FILE" ? seen && DONE_STATES.includes(seen.state) : !!seen;
    if (tx?.statusName === "FINALIZED" && tx.ok && decided) {
      a.status = "DONE"; a.verified_at = now; a.result = a.kind === "FILE" ? seen.state : "CLOSED";
      if (a.kind === "FILE") { a.refund = seen.refund_paid; a.reason = seen.reason; }
      run.done++; log(`DONE ${a.key} ${a.tx} -> ${a.result}`);
      return;
    }
    if (decided && !(tx?.statusName === "FINALIZED" && tx.ok)) {
      if (tx && tx.statusName !== "FINALIZED" && !TERMINAL_BAD.includes(tx.statusName)) {
        a.status = "ACCEPTED"; run.pending++; note(a.key, `decided in a read but ${a.tx} is ${tx.statusName}; waiting for FINALIZED`);
        return;
      }
      a.status = "DONE"; a.verified_at = now; a.result = a.kind === "FILE" ? seen.state : "CLOSED"; a.done_by_other = true;
      run.done++; log(`DONE ${a.key} (read shows it decided; our tx ${a.tx ?? "none"} ${tx?.statusName ?? ""})`);
      return;
    }
    if (tx?.statusName === "FINALIZED" && tx.ok && a.kind === "FILE" && seen?.state === "UNVERIFIABLE") {
      a.attempts++; a.last_error = "UNVERIFIABLE: " + (seen.reason ?? "") + " " + (seen.detail ?? "");
    } else if (tx?.statusName === "FINALIZED" && tx.ok) {
      a.status = "FINAL_UNVERIFIED"; run.pending++; note(a.key, "finalized, waiting for the read to show it");
      return;
    } else {
      a.attempts++; a.last_error = `tx ${a.tx} ${tx?.statusName ?? "not found"}${tx && !tx.ok ? " (reverted: " + (tx.reason ?? "") + ")" : ""}`;
    }
    a.tx = null;
    if (a.attempts >= MAX_ATTEMPTS) { a.status = "FAILED"; run.failed++; note(a.key, `gave up after ${a.attempts} attempts: ${a.last_error}`); }
    else { a.status = "RETRY"; a.next_try_at = now + backoffS(a.attempts); run.retry++; note(a.key, `retry ${a.attempts} after ${a.next_try_at}: ${a.last_error}`); }
    log(`RETRY ${a.key}: ${a.last_error}`);
  }

  // 1. resume
  for (const a of Object.values(state.actions)) {
    if (!["SUBMITTED", "ACCEPTED", "FINAL_UNVERIFIED"].includes(a.status)) continue;
    run.resumed++;
    if (a.status === "FINAL_UNVERIFIED") { await conclude(a, { statusName: "FINALIZED", ok: true }); await save("verify " + a.key); continue; }
    let tx = null;
    try { tx = await reg.getTx(a.tx); } catch (e) { a.last_error = "poll failed: " + e.message; run.pending++; note(a.key, "could not poll " + a.tx); continue; }
    if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) { await conclude(a, tx); await save("resolved " + a.key); continue; }
    if (reg.now() - a.submitted_at > STALE_S) {
      // no final status for 6 h: if the case got decided anyway it is done, else file it again
      log(`STALE ${a.key} ${a.tx} (${tx?.statusName ?? "not visible"} for ${reg.now() - a.submitted_at}s)`);
      await conclude(a, tx && tx.statusName === "FINALIZED" ? tx : { statusName: "STALE_" + (tx?.statusName ?? "MISSING"), ok: false });
      await save("stale " + a.key);
      continue;
    }
    a.status = tx?.statusName === "ACCEPTED" ? "ACCEPTED" : "SUBMITTED";
    run.pending++; note(a.key, `waiting for ${a.tx} (${tx?.statusName ?? "not visible yet"})`);
  }

  // 2. pools: every page, offset persisted
  const pools = [];
  let off = 0;
  for (;;) {
    let pg;
    try { pg = await reg.getPools(off, POOL_PAGE); } catch (e) { run.errors.push("get_pools " + off + ": " + e.message); note("pools", "pool listing failed at offset " + off); break; }
    for (const p of pg.items ?? []) pools.push(p);
    state.pools_offset = off;
    if (pg.next_offset === undefined || pg.next_offset < 0 || pg.next_offset <= off) break;
    off = pg.next_offset;
  }
  state.pools_total = pools.length;
  run.pools = pools.length;
  await save("pools listed");

  // 3. scan
  let pagesLeft = maxPages;
  for (const p of pools) {
    const pid = p.pool_id;
    const ps = (state.pools[pid] ??= { chains: {}, status: p.status });
    ps.status = p.status;
    ps.claim_deadline = p.claim_deadline;
    ps.name = p.name;
    const open = scanPools && p.status === "OPEN" && reg.now() <= p.claim_deadline;
    if (open) {
      for (const r of p.ranges) {
        const cs = (ps.chains[r.chain] ??= { cursor: r.start_block, failed: [], pages_ok: 0, done: false, head: 0 });
        const routers = new Set(p.routers.filter((x) => x.chain === r.chain).map((x) => x.address.toLowerCase()));
        const eps = scan.endpoints(r.chain);
        const hs = [];
        for (const u of eps) {
          if (hs.length === 2) break;
          try { hs.push(await scan.head(u, r.chain)); } catch { /* next endpoint */ }
        }
        if (hs.length < 2) { note(`scan:${pid}:${r.chain}`, "finalized head: fewer than two endpoints answered"); continue; }
        const head = Math.min(...hs);
        cs.head = head;
        const top = Math.min(r.end_block, head - 1);
        const pages = [...cs.failed.map((f) => [f, false]), ];
        cs.failed = [];
        for (let b = cs.cursor; b <= top && pages.length < pagesLeft; b += PAGE_BLOCKS) pages.push([b, true]);
        for (const [from, fresh] of pages) {
          if (pagesLeft <= 0) { cs.failed.push(from); continue; }
          pagesLeft--;
          const to = Math.min(from + PAGE_BLOCKS - 1, top);
          const got = await pageLogs(scan, eps, r.chain, from, to);
          run.pages++;
          if (!got.ok) {
            cs.failed.push(from); run.pages_failed++;
            note(`page:${pid}:${r.chain}:${from}`, `blocks ${from}-${to}: ${got.why}; retried next run`);
          } else {
            cs.pages_ok++;
            const cands = candidates(got.logs);
            if (cands.length) {
              const txs = await bothTxs(scan, eps, r.chain, cands);
              if (!txs.ok) { cs.failed.push(from); run.pages_failed++; note(`page:${pid}:${r.chain}:${from}`, "candidate transactions: " + txs.why); }
              else for (const t of txs.txs) if (routers.has(t.to)) addFile(pid, r.chain, t.hash, t.from, "scan");
            }
          }
          if (fresh) cs.cursor = Math.max(cs.cursor, to + 1);
          await save(`scan ${pid} ${r.chain} ${from}`);
        }
        cs.done = cs.cursor > r.end_block && cs.failed.length === 0;
        if (!cs.done) note(`scan:${pid}:${r.chain}`, `scanned to ${cs.cursor - 1} of ${r.end_block}${cs.failed.length ? ", " + cs.failed.length + " pages to retry" : ""}${cs.cursor > top && top < r.end_block ? " (finalized head " + head + ")" : ""}`);
        // watchlist hashes in this range
        const w = watch.filter((x) => x.chain === r.chain && !state.actions[fileKey(pid, r.chain, x.hash)]);
        if (w.length) {
          const txs = await bothTxs(scan, eps, r.chain, w.map((x) => x.hash));
          if (!txs.ok) note(`watch:${pid}:${r.chain}`, "watchlist transactions: " + txs.why);
          else for (const t of txs.txs) if (t.block >= r.start_block && t.block <= r.end_block) addFile(pid, r.chain, t.hash, t.from, "watchlist");
          await save("watchlist " + pid);
        }
      }
    }
    if (closable(p, reg.now()) && !state.actions[closeKey(pid)]) {
      state.actions[closeKey(pid)] = { key: closeKey(pid), kind: "CLOSE", pool_id: pid, sponsor: p.sponsor, status: "QUEUED", attempts: 0,
        first_seen_at: reg.now(), tx: null };
    }
  }

  // 4. act, oldest first
  const queue = Object.values(state.actions).filter((a) => a.status === "QUEUED" || (a.status === "RETRY" && reg.now() >= a.next_try_at))
    .sort((x, y) => x.first_seen_at - y.first_seen_at || (x.key < y.key ? -1 : 1));
  let acted = 0;
  for (const a of queue) {
    const pool = pools.find((p) => p.pool_id === a.pool_id);
    if (acted >= maxActions) { note(a.key, "queued; this run reached its action limit"); continue; }
    // already decided (by anyone)? then no transaction
    let seen = null;
    try { seen = await verify(a); } catch (e) { note(a.key, "pre-read failed: " + e.message); continue; }
    if (a.kind === "FILE" && seen && DONE_STATES.includes(seen.state)) {
      a.status = "DONE"; a.result = seen.state; a.refund = seen.refund_paid; a.reason = seen.reason; a.done_by_other = !a.tx_history?.length;
      a.verified_at = reg.now(); run.already++; run.done++; await save("already " + a.key); continue;
    }
    if (a.kind === "CLOSE" && seen) { a.status = "DONE"; a.result = "CLOSED"; a.verified_at = reg.now(); run.already++; run.done++; await save("already " + a.key); continue; }
    const inRecovery = pool && pool.status === "OPEN" && reg.now() > pool.claim_deadline && reg.now() <= (pool.recovery_deadline ?? 0)
      && seen?.state === "UNVERIFIABLE" && TRANSIENT.includes(seen.reason);
    if (a.kind === "FILE" && (!pool || pool.status !== "OPEN" || (reg.now() > pool.claim_deadline && !inRecovery))) {
      a.status = "FAILED"; a.last_error = "pool closed or past its claim deadline (and not a case pending in its recovery window)"; run.failed++;
      note(a.key, a.last_error); await save("expired " + a.key); continue;
    }
    acted++;
    try {
      a.tx = a.kind === "FILE" ? await reg.fileCase(a.pool_id, a.chain, a.hash, a.victim) : await reg.closePool(a.pool_id, a.sponsor);
    } catch (e) {
      a.attempts++; a.last_error = "submit failed: " + String(e.message).slice(0, 160);
      a.status = a.attempts >= MAX_ATTEMPTS ? "FAILED" : "RETRY"; a.next_try_at = reg.now() + backoffS(a.attempts);
      if (a.status === "FAILED") run.failed++; else run.retry++;
      note(a.key, a.last_error); await save("submit failed " + a.key); continue;
    }
    a.status = "SUBMITTED"; a.submitted_at = reg.now(); (a.tx_history ??= []).push(a.tx);
    run.submitted++;
    await save("submitted " + a.key);
    if (waitMs > 0 && reg.wait) {
      const tx = await reg.wait(a.tx, waitMs);
      if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) await conclude(a, tx);
      else { a.status = tx?.statusName === "ACCEPTED" ? "ACCEPTED" : "SUBMITTED"; run.pending++; note(a.key, `waiting for ${a.tx} (${tx?.statusName ?? "not visible"})`); }
      await save("waited " + a.key);
    } else { run.pending++; note(a.key, `submitted ${a.tx}; checked next run`); }
  }

  // 5. settle: poll what this run left in flight until it is final, within the budget
  const t0 = Date.now();
  while (settleMs > 0 && reg.sleep) {
    const open = Object.values(state.actions).filter((a) => ["SUBMITTED", "ACCEPTED", "FINAL_UNVERIFIED"].includes(a.status) && a.tx);
    if (!open.length || Date.now() - t0 > settleMs) break;
    await reg.sleep(15_000);
    for (const a of open) {
      let tx = null;
      try { tx = await reg.getTx(a.tx); } catch { continue; }
      if (tx && (tx.statusName === "FINALIZED" || TERMINAL_BAD.includes(tx.statusName))) {
        unprocessed.delete(a.key);
        run.pending = Math.max(0, run.pending - 1);
        await conclude(a, tx);
        await save("settled " + a.key);
      }
    }
  }

  for (const a of Object.values(state.actions)) if (a.status === "FAILED") note(a.key, "FAILED: " + (a.last_error ?? ""));
  run.finished_at = reg.now();
  state.unprocessed = [...unprocessed.values()];
  state.last_run = run;
  state.runs = [...(state.runs ?? []), { ...run, errors: run.errors.slice(0, 5) }].slice(-48);
  state.totals = totals(state);
  await save("run finished");
  return { run, state };
}

export function totals(state) {
  const t = { actions: 0, done: 0, queued: 0, pending: 0, retry: 0, failed: 0, by_result: {} };
  for (const a of Object.values(state.actions)) {
    t.actions++;
    if (a.status === "DONE") { t.done++; t.by_result[a.result] = (t.by_result[a.result] ?? 0) + 1; }
    else if (a.status === "QUEUED") t.queued++;
    else if (a.status === "RETRY") t.retry++;
    else if (a.status === "FAILED") t.failed++;
    else t.pending++;
  }
  return t;
}

/** One page of Swap logs from two endpoints that must both answer and agree. */
export async function pageLogs(scan, eps, chain, from, to) {
  const res = [];
  const why = [];
  for (const u of eps) {
    if (res.length === 2) break;
    try { res.push(await scan.getLogs(u, chain, from, to)); } catch (e) { why.push(hostOf(u) + ": " + String(e.message).slice(0, 60)); }
  }
  if (res.length < 2) return { ok: false, why: "fewer than two endpoints answered (" + why.join("; ") + ")" };
  const a = res[0].map(logKey).sort().join(","), b = res[1].map(logKey).sort().join(",");
  if (a !== b) return { ok: false, why: "the two endpoints returned different logs" };
  return { ok: true, logs: res[0] };
}

/** Transactions from two endpoints that must agree on from/to/block. */
export async function bothTxs(scan, eps, chain, hashes) {
  const res = [];
  const why = [];
  for (const u of eps) {
    if (res.length === 2) break;
    try { res.push(await scan.getTxs(u, chain, hashes)); } catch (e) { why.push(hostOf(u) + ": " + String(e.message).slice(0, 60)); }
  }
  if (res.length < 2) return { ok: false, why: "fewer than two endpoints answered (" + why.join("; ") + ")" };
  const norm = (t) => (t ? { hash: String(t.hash).toLowerCase(), from: String(t.from).toLowerCase(), to: t.to ? String(t.to).toLowerCase() : "",
    block: Number(t.blockNumber) } : null);
  const A = res[0].map(norm), B = res[1].map(norm);
  if (JSON.stringify(A) !== JSON.stringify(B)) return { ok: false, why: "the two endpoints disagree on a transaction" };
  return { ok: true, txs: A.filter(Boolean) };
}

const hostOf = (u) => { try { return new URL(u).host; } catch { return u; } };
export { SWAP_V2, SWAP_V3 };
