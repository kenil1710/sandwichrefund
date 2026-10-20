// The off-chain mirror of the contract's read and rule (contracts/shared/rpc.py
// read_facts / common.py judge). The keeper uses it to pick candidates and the
// feasibility study to read every case from two RPCs; the contract decides.
// test/keeper.test.mjs and test_meaning.py run both on the same fixtures.
import { CHAINS, SWAP_V2, SWAP_V3, FACTORIES } from "./chains.mjs";

export const BATCH_MAX = 12;
export const MAX_POOLS = 4;        // victim swap pools read per case
export const MAX_TXS = 40;         // other transactions on the victim's pools in its block
export const ZERO = "0x" + "0".repeat(40);

const lc = (v) => String(v ?? "").toLowerCase();
const hexInt = (v) => (typeof v === "string" && /^0x[0-9a-fA-F]+$/.test(v) ? BigInt(v) : -1n);
const word = (d, i) => d.slice(2 + 64 * i, 2 + 64 * i + 64);
const s256 = (h) => { let v = BigInt("0x" + h); if (v >= 1n << 255n) v -= 1n << 256n; return v; };
const topicAddr = (t) => (typeof t === "string" && t.length === 66 && /^0x0{24}/.test(t) ? "0x" + t.slice(26).toLowerCase() : "");
const wordAddr = (r) => (typeof r === "string" && r.length === 66 && /^0x0{24}/.test(r) ? "0x" + r.slice(26).toLowerCase() : "");

export class ReadFailed extends Error {}

/** One endpoint, every call, in batches of BATCH_MAX. Any error -> ReadFailed. */
export async function rpcSend(url, calls, { tries = 4, fetchImpl = fetch } = {}) {
  const out = [];
  for (let i = 0; i < calls.length; i += BATCH_MAX) {
    const chunk = calls.slice(i, i + BATCH_MAX);
    const body = JSON.stringify(chunk.map((c, j) => ({ jsonrpc: "2.0", id: j, method: c[0], params: c[1] })));
    let got = null, why = "";
    for (let t = 0; t < tries && got === null; t++) {
      try {
        const r = await fetchImpl(url, { method: "POST", headers: { "content-type": "application/json" }, body, signal: AbortSignal.timeout(30000) });
        if (r.status !== 200) { why = "http " + r.status; if (r.status !== 429 && r.status < 500) break; await new Promise((s) => setTimeout(s, 1500 * (t + 1))); continue; }
        let doc = await r.json();
        if (!Array.isArray(doc)) doc = [doc];
        const byId = new Map(doc.filter((x) => x && Number.isInteger(x.id)).map((x) => [x.id, x]));
        const res = [];
        for (let j = 0; j < chunk.length; j++) {
          const it = byId.get(j);
          if (!it) throw new ReadFailed("missing id");
          if (it.error) throw new ReadFailed("rpc error " + JSON.stringify(it.error).slice(0, 80));
          if (!("result" in it)) throw new ReadFailed("no result");
          res.push(it.result);
        }
        got = res;
      } catch (e) { why = String(e?.message ?? e).slice(0, 80); await new Promise((s) => setTimeout(s, 1500 * (t + 1))); }
    }
    if (got === null) throw new ReadFailed(why);
    out.push(...got);
  }
  return out;
}

/** A Swap log -> {pool, kind, n0, n1, sender, recipient, ti, li, tx, block} (amounts as the pool sees them: + received, - sent), or null. */
export function decodeSwap(l) {
  const t = l?.topics;
  if (!Array.isArray(t) || t.length !== 3) return null;
  const t0 = lc(t[0]);
  const d = lc(l.data);
  const sender = topicAddr(lc(t[1])), recipient = topicAddr(lc(t[2]));
  const pool = lc(l.address);
  const ti = hexInt(l.transactionIndex), li = hexInt(l.logIndex), block = hexInt(l.blockNumber);
  if (!sender || !recipient || pool.length !== 42 || ti < 0n || li < 0n || block < 0n) return null;
  let kind, n0, n1;
  if (t0 === SWAP_V2) {
    if (d.length !== 2 + 64 * 4) return null;
    kind = "V2";
    n0 = BigInt("0x" + word(d, 0)) - BigInt("0x" + word(d, 2));
    n1 = BigInt("0x" + word(d, 1)) - BigInt("0x" + word(d, 3));
  } else if (t0 === SWAP_V3) {
    if (d.length !== 2 + 64 * 5) return null;
    kind = "V3";
    n0 = s256(word(d, 0));
    n1 = s256(word(d, 1));
  } else return null;
  return { pool, kind, n0: String(n0), n1: String(n1), sender, recipient, ti: Number(ti), li: Number(li), tx: lc(l.transactionHash), block: Number(block) };
}

/** Facts about one victim transaction from ONE endpoint. Same shape as the contract's projection. */
export async function readFacts(url, chain, hash, opts = {}) {
  const cid = CHAINS[chain].id;
  const a = await rpcSend(url, [["eth_getTransactionByHash", [hash]], ["eth_getTransactionReceipt", [hash]],
    ["eth_getBlockByNumber", ["finalized", false]], ["eth_chainId", []]], opts);
  if (hexInt(a[3]) !== BigInt(cid)) return { reason: "WRONG_CHAIN_ID" };
  const fin = hexInt(a[2]?.number);
  if (fin < 0n) throw new ReadFailed("no finalized head");
  const tx = a[0], rc = a[1];
  if (tx === null) return { reason: "TX_NOT_FOUND" };
  if (rc === null) return { reason: "TX_PENDING" };
  const block = hexInt(rc.blockNumber), ti = hexInt(rc.transactionIndex);
  const bh = lc(rc.blockHash);
  if (block < 0n || ti < 0n || bh.length !== 66 || lc(tx.blockHash) !== bh || hexInt(tx.blockNumber) !== block) return { reason: "RPC_UNREADABLE" };
  const head = { hash: lc(hash), block: Number(block), block_hash: bh, index: Number(ti), status: lc(rc.status) === "0x1" ? 1 : 0,
    from: lc(tx.from), to: tx.to ? lc(tx.to) : "" };
  const vs = [];
  for (const l of rc.logs ?? []) {
    const s = decodeSwap(l);
    if (s) vs.push({ pool: s.pool, kind: s.kind, li: s.li, n0: s.n0, n1: s.n1, sender: s.sender, recipient: s.recipient });
  }
  const base = { tx: head, finalized: Number(fin), victim_swaps: vs, pools: [], swaps: [], flags: [] };
  const poolKind = {};
  for (const s of vs) poolKind[s.pool] = s.kind;
  const pools = Object.keys(poolKind).sort();
  if (head.status !== 1 || pools.length === 0) return base;
  if (pools.length > MAX_POOLS) { base.flags.push("TOO_MANY_POOLS"); return base; }
  if (Number(block) + 1 > Number(fin)) return base;           // judged NOT_FINALIZED; nothing more to read
  const bhex = "0x" + block.toString(16), nhex = "0x" + (block + 1n).toString(16);
  const calls = [["eth_getLogs", [{ address: pools, topics: [[SWAP_V2, SWAP_V3]], fromBlock: bhex, toBlock: nhex }]]];
  for (const p of pools) {
    calls.push(["eth_call", [{ to: p, data: "0x0dfe1681" }, "latest"]], ["eth_call", [{ to: p, data: "0xd21220a7" }, "latest"]],
      ["eth_call", [{ to: p, data: "0xc45a0155" }, "latest"]]);
    if (poolKind[p] === "V3") calls.push(["eth_call", [{ to: p, data: "0xddca3f43" }, "latest"]]);
  }
  const b = await rpcSend(url, calls, opts);
  const logs = b[0];
  if (!Array.isArray(logs)) throw new ReadFailed("logs");
  let k = 1;
  const pinfo = [];
  for (const p of pools) {
    const t0 = wordAddr(lc(b[k])), t1 = wordAddr(lc(b[k + 1])), f = wordAddr(lc(b[k + 2]));
    k += 3;
    let fee = 0;
    if (poolKind[p] === "V3") { fee = Number(hexInt(b[k])); k += 1; }
    if (!t0 || !t1 || !f || fee < 0) return { reason: "RPC_UNREADABLE" };
    pinfo.push({ address: p, kind: poolKind[p], token0: t0, token1: t1, factory: f, fee, canonical: false });
  }
  const swaps = [];
  for (const l of logs) {
    const s = decodeSwap(l);
    if (!s || !pools.includes(s.pool) || (s.block !== Number(block) && s.block !== Number(block) + 1)) continue;
    if (s.kind !== poolKind[s.pool]) continue;
    swaps.push({ ...s, from: "", to: "" });
  }
  swaps.sort((x, y) => x.block - y.block || x.li - y.li);
  const others = [...new Set(swaps.filter((s) => s.block === Number(block) && s.tx !== lc(hash)).map((s) => s.tx))].sort();
  if (others.length > MAX_TXS) { base.pools = pinfo; base.flags.push("BLOCK_TOO_BUSY"); return base; }
  const c2 = [];
  const fcheck = [];
  for (const p of pinfo) {
    if (!(FACTORIES[chain]?.[p.kind] ?? []).includes(p.factory)) continue;
    const pad = (a) => a.slice(2).padStart(64, "0");
    const data = p.kind === "V2" ? "0xe6a43905" + pad(p.token0) + pad(p.token1)
      : "0x1698ee82" + pad(p.token0) + pad(p.token1) + BigInt(p.fee).toString(16).padStart(64, "0");
    c2.push(["eth_call", [{ to: p.factory, data }, "latest"]]);
    fcheck.push(p);
  }
  for (const h of others) c2.push(["eth_getTransactionByHash", [h]]);
  const c = c2.length ? await rpcSend(url, c2, opts) : [];
  fcheck.forEach((p, i) => { p.canonical = wordAddr(lc(c[i])) === p.address; });
  const fromOf = {};
  others.forEach((h, i) => {
    const t = c[fcheck.length + i];
    if (!t || lc(t.hash) !== h) throw new ReadFailed("tx " + h.slice(0, 10));
    fromOf[h] = { from: lc(t.from), to: t.to ? lc(t.to) : "" };
  });
  for (const s of swaps) {
    if (s.block !== Number(block)) continue;
    if (s.tx === lc(hash)) { s.from = head.from; s.to = head.to; }
    else { s.from = fromOf[s.tx].from; s.to = fromOf[s.tx].to; }
  }
  base.pools = pinfo;
  base.swaps = swaps;
  return base;
}

const canon = (v) => JSON.stringify(v, Object.keys(flatKeys(v)).sort());
function flatKeys(v, acc = {}) { if (v && typeof v === "object") for (const [k, x] of Object.entries(v)) { acc[k] = 1; flatKeys(x, acc); } return acc; }

/** Both endpoints of a chain -> {facts} if they agree, else {reason, detail}. */
export async function readBoth(chain, hash, opts = {}) {
  const views = [];
  for (const url of opts.rpcs ?? CHAINS[chain].rpcs) {
    try { views.push(await readFacts(url, chain, hash, opts)); }
    catch (e) { return { reason: "RPC_UNREADABLE", detail: new URL(url).host + ": " + String(e?.message ?? e).slice(0, 60) }; }
  }
  const [a, b] = views;
  if (a.reason || b.reason) {
    if (a.reason && a.reason === b.reason) return { reason: a.reason, detail: "" };
    return { reason: "RPC_DISAGREE", detail: "one RPC has the transaction, the other does not" };
  }
  const strip = (f) => ({ ...f, finalized: 0 });
  if (canon(strip(a)) !== canon(strip(b))) return { reason: "RPC_DISAGREE", detail: "the two RPCs answer differently" };
  return { facts: { ...a, finalized: Math.min(a.finalized, b.finalized) } };
}

// ---------------------------------------------------------------------------
// the rule

const dirOf = (s) => { const a = BigInt(s.n0), b = BigInt(s.n1); return a > 0n && b < 0n ? 0 : b > 0n && a < 0n ? 1 : -1; };
const amt = (s, i) => BigInt(i === 0 ? s.n0 : s.n1);

/** Conservative attacker profit from one front-run f and back-run b around a victim trading direction d.
 *  -> {token: 0|1 (index), amount} or null. */
export function attackerProfit(f, b, d) {
  const e = 1 - d;
  const fXin = amt(f, d), fYout = -amt(f, e), bYin = amt(b, e), bXout = -amt(b, d);
  if (fXin <= 0n || fYout <= 0n || bYin <= 0n || bXout <= 0n) return null;
  const netX = bXout - fXin, netY = fYout - bYin;
  if (netX > 0n && netY >= 0n) return { token: d, amount: netX, alt: netY > 0n ? { token: e, amount: netY } : null };
  if (netY > 0n && netX >= 0n) return { token: e, amount: netY, alt: null };
  if (netX > 0n && netY < 0n) { const px = (bXout * fYout) / bYin - fXin; return px > 0n ? { token: d, amount: px, alt: null } : null; }
  if (netY > 0n && netX < 0n) { const need = (bYin * fXin + bXout - 1n) / bXout; const py = fYout - need; return py > 0n ? { token: e, amount: py, alt: null } : null; }
  return null;
}

/**
 * terms: {chain, routers:[addr], kinds:["V2","V3"], start_block, end_block, rates:{token:[num,den]}}
 * r: readBoth() answer. -> {verdict, reason, ...detail}
 * verdict: UNVERIFIABLE | NOT_COVERED | CLEAN | UNCLEAR | SANDWICHED
 */
export function judge(terms, r) {
  if (r.reason) return { verdict: "UNVERIFIABLE", reason: r.reason };
  const f = r.facts, t = f.tx;
  const out = (verdict, reason, extra = {}) => ({ verdict, reason, block: t.block, index: t.index, victim: t.from, router: t.to, ...extra });
  if (t.block + 1 > f.finalized) return out("UNVERIFIABLE", "NOT_FINALIZED");
  if (t.status !== 1) return out("NOT_COVERED", "TX_FAILED");
  if (!terms.routers.includes(t.to)) return out("NOT_COVERED", "ROUTER_NOT_COVERED");
  if (t.block < terms.start_block || t.block > terms.end_block) return out("NOT_COVERED", "OUTSIDE_BLOCK_RANGE");
  const vs = f.victim_swaps.filter((s) => terms.kinds.includes(s.kind));
  if (vs.length === 0) return out("NOT_COVERED", f.victim_swaps.length ? "POOL_TYPE_NOT_COVERED" : "NO_SWAP_IN_TX");
  if (f.flags.includes("TOO_MANY_POOLS")) return out("UNCLEAR", "TOO_MANY_HOPS");
  if (f.flags.includes("BLOCK_TOO_BUSY")) return out("UNCLEAR", "BLOCK_TOO_BUSY");
  const pinfo = Object.fromEntries(f.pools.map((p) => [p.address, p]));
  const good = vs.filter((s) => pinfo[s.pool]?.canonical);
  if (vs.length === 1 && good.length === 0) return out("NOT_COVERED", "POOL_NOT_CANONICAL", { pool: vs[0].pool });
  const exclude = new Set([ZERO, t.to, ...terms.routers, ...f.pools.map((p) => p.address)]);
  if (vs.length > 1) {
    for (const s of good) {
      const a = analyzePool(f, s, exclude);
      if (a.pairs.length > 0 || a.partial) return out("UNCLEAR", "MULTI_HOP_VICTIM", { pool: s.pool });
    }
    return out("CLEAN", "NO_PATTERN", { pool: good[0]?.pool ?? vs[0].pool, hops: vs.length });
  }
  const v = good[0];
  const d = dirOf(v);
  if (d < 0) return out("UNCLEAR", "VICTIM_DIRECTION_UNREADABLE", { pool: v.pool });
  const a = analyzePool(f, v, exclude);
  const P = pinfo[v.pool];
  const base = { pool: v.pool, kind: v.kind, direction: d, token_in: d === 0 ? P.token0 : P.token1, token_out: d === 0 ? P.token1 : P.token0,
    victim_n0: v.n0, victim_n1: v.n1 };
  if (a.pairs.length === 0) {
    if (a.partial) return out("UNCLEAR", a.partial, base);
    return out("CLEAN", "NO_PATTERN", base);
  }
  const clusters = cluster(a.pairs, exclude);
  if (clusters.length > 1) return out("UNCLEAR", "MULTIPLE_ATTACKERS", { ...base, attackers: clusters.length });
  const fronts = [...new Set(clusters[0].map((p) => p.f.li))], backs = [...new Set(clusters[0].map((p) => p.b.li))];
  if (fronts.length > 1 || backs.length > 1) return out("UNCLEAR", "COMPLEX_PATTERN", base);
  const { f: fr, b: bk } = clusters[0][0];
  const att = { front_tx: fr.tx, front_index: fr.ti, back_tx: bk.tx, back_index: bk.ti, attacker_eoa: fr.from, attacker_contract: fr.to,
    attacker_recipient: fr.recipient, front_n0: fr.n0, front_n1: fr.n1, back_n0: bk.n0, back_n1: bk.n1 };
  if ([fr.from, bk.from, fr.recipient, bk.recipient, fr.to, bk.to].some((x) => x === t.from || x === v.recipient))
    return out("UNCLEAR", "SELF_SANDWICH", { ...base, ...att });
  const between = a.same.filter((s) => s.ti > fr.ti && s.ti < bk.ti && s.tx !== t.hash && dirOf(s) === d && !sameActor(s, fr));
  if (between.length > 0) return out("UNCLEAR", "MULTIPLE_VICTIMS", { ...base, ...att, others: between.length });
  const pr = attackerProfit(fr, bk, d);
  if (!pr) return out("UNCLEAR", "NO_ATTACKER_PROFIT", { ...base, ...att });
  let pick = pr;
  const tok = (i) => (i === 0 ? P.token0 : P.token1);
  if (!terms.rates[tok(pick.token)] && pr.alt && terms.rates[tok(pr.alt.token)]) pick = pr.alt;
  const pt = tok(pick.token);
  if (!terms.rates[pt]) return out("UNCLEAR", "PROFIT_TOKEN_NOT_PRICED", { ...base, ...att, profit_token: pt, profit: String(pick.amount) });
  return out("SANDWICHED", "SAME_POOL_SANDWICH", { ...base, ...att, profit_token: pt, profit: String(pick.amount) });
}

function sameActor(s, x) {
  return s.from === x.from || s.recipient === x.recipient;
}

/** The victim's pool in its block: matched front/back pairs, and whether anything partial is there. */
export function analyzePool(f, v, exclude) {
  const t = f.tx;
  const d = dirOf(v);
  const same = f.swaps.filter((s) => s.pool === v.pool && s.block === t.block && s.tx !== t.hash);
  const next = f.swaps.filter((s) => s.pool === v.pool && s.block === t.block + 1);
  const before = same.filter((s) => s.ti < t.index), after = same.filter((s) => s.ti > t.index);
  const link = (x, y) => x.from === y.from || (x.recipient === y.recipient && !exclude.has(x.recipient));
  const pairs = [];
  if (d >= 0) for (const x of before) if (dirOf(x) === d) for (const y of after) if (dirOf(y) === 1 - d && link(x, y)) pairs.push({ f: x, b: y });
  let partial = "";
  if (pairs.length === 0) {
    for (const x of before) for (const y of after) if (link(x, y)) partial = "PARTIAL_PATTERN";
    if (!partial && d >= 0) for (const x of before) if (dirOf(x) === d && !exclude.has(x.recipient))
      for (const y of next) if (y.recipient === x.recipient && dirOf(y) === 1 - d) partial = "CROSS_BLOCK_PATTERN";
  }
  return { pairs, partial, same };
}

function cluster(pairs, exclude) {
  const groups = [];
  for (const p of pairs) {
    const ids = new Set([p.f.from, p.b.from, p.f.recipient, p.b.recipient].filter((x) => !exclude.has(x)));
    const hit = groups.filter((g) => g.ids.some((i) => ids.has(i)));
    const merged = { ids: [...ids, ...hit.flatMap((g) => g.ids)], pairs: [p, ...hit.flatMap((g) => g.pairs)] };
    for (const h of hit) groups.splice(groups.indexOf(h), 1);
    groups.push(merged);
  }
  return groups.map((g) => g.pairs);
}
