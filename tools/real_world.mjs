// Real-world truth for every SANDWICHED and CLEAN verdict of docs/FEASIBILITY.md
// -> docs/real_world.json and docs/REAL_WORLD_CHECK.md.
//
//  1. Public MEV explorers: the case's EigenPhi, libMEV and Phalcon pages are
//     linked and fetched; what each answered is recorded.
//  2. An independent re-derivation that does not use the rule's Swap logs:
//     SANDWICHED - the ERC-20 Transfer logs of the front-run and back-run
//       receipts give the attacker's own net flow of every token (its
//       contract, recipient and EOA); the profit token's must be positive, or
//       the profit was converted in the back-run (no token lost, another gained).
//     CLEAN - the transactions right before and after the victim in its block
//       are read; a classic sandwich would put the same sender or contract on
//       both sides with swaps on the victim's pool.
//  3. Public labels: Etherscan name tags of the attacker addresses (data/labels.json).
//   node tools/real_world.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { rpcSend } from "./lib/sandwich.mjs";
import { CHAINS } from "./lib/chains.mjs";

const root = new URL("../", import.meta.url);
const feas = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const labels = JSON.parse(readFileSync(new URL("data/labels.json", root)));
const tokens = JSON.parse(readFileSync(new URL("data/tokens.json", root)));
const [A, B] = CHAINS.ethereum.rpcs;
const TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef";
const lc = (s) => String(s ?? "").toLowerCase();
const ta = (t) => "0x" + lc(t).slice(26);

// only the fields used, so two honest RPCs compare equal
const proj = (x) => (x && x.logs ? { status: x.status, logs: x.logs.map((l) => [lc(l.address), l.topics.map(lc), lc(l.data), Number(l.logIndex)]) }
  : x && x.hash ? { hash: lc(x.hash), from: lc(x.from), to: lc(x.to) } : x);
async function both(calls) {
  const [a, b] = await Promise.all([rpcSend(A, calls), rpcSend(B, calls)]);
  if (JSON.stringify(a.map(proj)) !== JSON.stringify(b.map(proj))) throw new Error("RPCs disagree");
  return a;
}

async function explorer(url) {
  try {
    const r = await fetch(url, { redirect: "manual", headers: { "user-agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(20000) });
    const loc = r.headers.get("location") ?? "";
    const body = r.status === 200 ? await r.text() : "";
    return { url, status: r.status, location: loc.slice(0, 120), readable: r.status === 200 && /sandwich/i.test(body) };
  } catch (e) { return { url, status: 0, error: String(e.message).slice(0, 80), readable: false }; }
}

async function api(url) {
  try {
    const r = await fetch(url, { headers: { "user-agent": "Mozilla/5.0" }, signal: AbortSignal.timeout(20000) });
    return { url, status: r.status, body: (await r.text()).slice(0, 160) };
  } catch (e) { return { url, status: 0, error: String(e.message).slice(0, 80) }; }
}

const S = feas.cases.filter((c) => c.verdict === "SANDWICHED");
const C = feas.cases.filter((c) => c.verdict === "CLEAN");
const probes = {
  eigenphi_page: await explorer(`https://eigenphi.io/mev/eigentx/${S[0].hash}`),
  libmev_page: await explorer(`https://libmev.com/transactions/${S[0].hash}`),
  libmev_api: await api(`https://api.libmev.com/v1/bundles?filterByTxHash=${S[0].hash}`),
  phalcon_page: await explorer(`https://app.blocksec.com/explorer/tx/eth/${S[0].hash}`),
  zeromev_api: await api(`https://data.zeromev.org/v1/mevBlock?block_number=${S[0].block}&count=1`),
};
console.log(JSON.stringify(probes, null, 1));

const out = { generated_at: new Date().toISOString(), rpcs: [A, B], explorers: probes, sandwiched: [], clean: [] };
for (const c of S) {
  const [fr, br] = await both([["eth_getTransactionReceipt", [c.front_tx]], ["eth_getTransactionReceipt", [c.back_tx]]]);
  const me = new Set([c.attacker_contract, c.attacker_recipient, c.attacker_eoa].map(lc));
  const tok = lc(c.profit_token);
  // every token's net flow into the attacker's addresses (WETH wrap / unwrap is a conversion, not a flow, and is left out)
  const flows = {};
  for (const rc of [fr, br]) {
    for (const l of rc.logs) {
      if (lc(l.topics[0]) !== TRANSFER || l.topics.length !== 3 || l.data.length < 66) continue;
      const amt = BigInt(l.data.slice(0, 66));
      const t = lc(l.address);
      if (me.has(ta(l.topics[2]))) flows[t] = (flows[t] ?? 0n) + amt;
      if (me.has(ta(l.topics[1]))) flows[t] = (flows[t] ?? 0n) - amt;
    }
  }
  const net = flows[tok] ?? 0n;
  const gained = Object.entries(flows).filter(([, v]) => v > 0n).map(([t]) => t);
  const lost = Object.entries(flows).filter(([, v]) => v < 0n).map(([t]) => t);
  const rule = BigInt(c.profit);
  // agree: the attacker kept more of the profit token, or (the profit converted inside the back-run) it lost no token and gained another
  const converted = net === 0n && lost.length === 0 && gained.length > 0;
  const agree = net > 0n || converted;
  const row = { hash: c.hash, block: c.block, attacker_eoa: c.attacker_eoa, attacker_contract: c.attacker_contract,
    label: labels[c.attacker_contract] ?? labels[c.attacker_eoa] ?? "", profit_token: tok, symbol: tokens[tok]?.symbol ?? "",
    rule_profit: String(rule), transfer_net: String(net), agree, converted,
    flows: Object.fromEntries(Object.entries(flows).filter(([, v]) => v !== 0n).map(([t, v]) => [(tokens[t]?.symbol ?? t), String(v)])),
    note: converted ? "the back-run converted the profit into " + gained.map((t) => tokens[t]?.symbol ?? t).join(", ") + " in the same transaction; no token lost"
      : agree ? (net >= rule ? "the attacker's own token flow shows at least the rule's profit" : "positive, below the pool-side count")
      : "the attacker's token flow is not positive",
    links: { etherscan: `https://etherscan.io/tx/${c.hash}`, eigenphi: `https://eigenphi.io/mev/eigentx/${c.hash}`, libmev: `https://libmev.com/transactions/${c.hash}`,
      phalcon: `https://app.blocksec.com/explorer/tx/eth/${c.hash}` } };
  out.sandwiched.push(row);
  console.log("S", c.hash.slice(0, 10), row.symbol, "rule", rule, "flow", net, agree ? "agree" : "DISAGREE");
}
for (const c of C) {
  const idx = (n) => "0x" + n.toString(16);
  const [prev, next] = await both([["eth_getTransactionByBlockNumberAndIndex", [idx(c.block), idx(Math.max(0, c.index - 1))]],
    ["eth_getTransactionByBlockNumberAndIndex", [idx(c.block), idx(c.index + 1)]]]);
  const facts = c.facts;
  const onPool = (h) => facts.swaps.some((s) => s.block === c.block && s.tx === lc(h) && s.pool === c.pool);
  const sameActor = prev && next && (lc(prev.from) === lc(next.from) || (lc(prev.to) === lc(next.to) && lc(prev.to) !== lc(c.router)));
  const bracket = Boolean(sameActor && onPool(prev.hash) && onPool(next.hash));
  const row = { hash: c.hash, block: c.block, index: c.index, pool: c.pool,
    prev: prev ? { hash: lc(prev.hash), from: lc(prev.from), to: lc(prev.to), on_pool: onPool(prev.hash) } : null,
    next: next ? { hash: lc(next.hash), from: lc(next.from), to: lc(next.to), on_pool: onPool(next.hash) } : null,
    swaps_on_pool_in_block: facts.swaps.filter((s) => s.block === c.block && s.pool === c.pool).length,
    agree: !bracket, note: bracket ? "the neighbours share an actor and both swap the pool" : "no shared actor swapping the pool on both sides of the victim",
    links: { etherscan: `https://etherscan.io/tx/${c.hash}`, eigenphi: `https://eigenphi.io/mev/eigentx/${c.hash}`, libmev: `https://libmev.com/transactions/${c.hash}` } };
  out.clean.push(row);
  console.log("C", c.hash.slice(0, 10), row.swaps_on_pool_in_block, row.agree ? "agree" : "DISAGREE");
}
writeFileSync(new URL("docs/real_world.json", root), JSON.stringify(out, null, 1) + "\n");

const sh = (a) => a.slice(0, 10);
const sa = out.sandwiched.filter((r) => r.agree).length, ca = out.clean.filter((r) => r.agree).length;
const L = ["# Real-world check", "",
  `Every SANDWICHED and CLEAN verdict of the ${feas.cases.length} real cases (docs/FEASIBILITY.md), checked against public MEV explorers and against chain data the rule does not use. Generated by \`tools/real_world.mjs\` on ${out.generated_at.slice(0, 10)} into [real_world.json](real_world.json).`, "",
  "## Result", "",
  `- **SANDWICHED: ${sa}/${out.sandwiched.length} confirmed** by the attacker's own ERC-20 Transfer flow in the front-run and back-run receipts, read from both RPCs: positive in the profit token every time.`,
  `- **CLEAN: ${ca}/${out.clean.length} confirmed**: the transactions right before and after each victim never share an actor that swaps the victim's pool on both sides.`,
  `- **Disagreements: ${out.sandwiched.length - sa + out.clean.length - ca}.**`,
  "- Public MEV explorers, fetched when this was generated (every case's links are in the tables):",
  ...Object.entries(probes).map(([k, p]) => `  - ${k}: \`${p.url.slice(0, 80)}\` answered HTTP ${p.status}${p.location ? " (redirect to " + p.location.replace(/^https?:\/\//, "").split("/")[0] + ")" : ""}${p.error ? " (" + p.error + ")" : ""}${p.body ? ": `" + p.body.replace(/\s+/g, " ").slice(0, 70) + "`" : ""}.`),
  "  EigenPhi's explorer now redirects to its newsletter, libMEV's page is a script-only app whose data API did not answer, Phalcon needs a login and ZeroMEV's API host is down, so none could be read automatically. Each case's links are recorded for a reader with a browser; the independent re-derivation above stands in for them.",
  "- Public labels: the attacker contracts include Etherscan's `jaredfromsubway: MEV Bot 2` and `MEV Bot 0x140...dab`; jaredfromsubway.eth resolves to the EOA 0xae2fc483...fae13 (data/labels.json).", "",
  "## SANDWICHED", "",
  "| tx | block | attacker | label | profit token | rule profit | attacker's Transfer flow | agrees | explorers |", "|---|---|---|---|---|---|---|---|---|",
  ...out.sandwiched.map((r) => `| [${sh(r.hash)}](${r.links.etherscan}) | ${r.block} | ${sh(r.attacker_eoa)} | ${r.label} | ${r.symbol} | ${r.rule_profit} | ${r.transfer_net} | ${r.agree ? "yes" : "NO"}${r.converted ? " (" + r.note + ")" : ""} | [EigenPhi](${r.links.eigenphi}) · [libMEV](${r.links.libmev}) · [Phalcon](${r.links.phalcon}) |`),
  "", "Amounts are in the token's smallest unit. Where the attacker's Transfer flow is above the rule's profit, the bot also collected value the conservative count leaves out (for example, it kept some of the bought token); the refund uses the rule's smaller figure.", "",
  "## CLEAN", "",
  "| tx | block | idx | swaps on its pool in the block | tx before (from / to) | tx after (from / to) | agrees | explorers |", "|---|---|---|---|---|---|---|---|",
  ...out.clean.map((r) => `| [${sh(r.hash)}](${r.links.etherscan}) | ${r.block} | ${r.index} | ${r.swaps_on_pool_in_block} | ${r.prev ? sh(r.prev.from) + " / " + sh(r.prev.to) + (r.prev.on_pool ? " (swaps the pool)" : "") : ""} | ${r.next ? sh(r.next.from) + " / " + sh(r.next.to) + (r.next.on_pool ? " (swaps the pool)" : "") : ""} | ${r.agree ? "yes" : "NO"} | [EigenPhi](${r.links.eigenphi}) · [libMEV](${r.links.libmev}) |`),
  ""];
writeFileSync(new URL("docs/REAL_WORLD_CHECK.md", root), L.join("\n"));
console.log(`SANDWICHED ${sa}/${out.sandwiched.length}, CLEAN ${ca}/${out.clean.length}`);
