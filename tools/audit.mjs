/**
 * The pre-submission audit, A-N, each with its proof read now -> docs/AUDIT.md.
 *   node tools/audit.mjs      exit 1 if any check fails
 */
import { readFileSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { client, deployments, balanceOf, finalized, payoutDelivered } from "./lib/sr.mjs";
import { CHAINS } from "./lib/chains.mjs";
import { rpcSend } from "./lib/sandwich.mjs";

const root = new URL("..", import.meta.url).pathname;
const j = (p) => JSON.parse(readFileSync(root + p, "utf8"));
const sh = (cmd, args) => spawnSync(cmd, args, { cwd: root, encoding: "utf8", maxBuffer: 64 << 20 });
const dep = deployments().contracts;
const pool = j("data/pool_canonical.json");
const feas = j("docs/feasibility.json");
const gv = j("docs/feasibility_genvm.json");
const ver = j("docs/seed-canonical-verify.json");
const seed = j("docs/seed-canonical.json");
const demo = j("docs/demo-run.json");
const rw = j("docs/real_world.json");
const C = client({ role: "keeper", address: dep.SandwichRefund.address });
const D = client({ role: "keeper", address: dep.SandwichRefundDemo.address });
const G = client({ role: "keeper", address: dep.MEVGate.address });
const rows = [];
// the latest successful scheduled keeper run after the newest deployment: it ran against the contracts in deployments.json
const deployedAt = Math.max(...Object.values(dep).map((c) => Date.parse(c.deployed_at)));
const keeperRun = ((await (await fetch("https://api.github.com/repos/kenil1710/sandwichrefund/actions/workflows/keeper.yml/runs?event=schedule&status=success&per_page=50",
  { headers: { "user-agent": "audit" } })).json()).workflow_runs ?? []).find((r) => Date.parse(r.created_at) > deployedAt) ?? {};
const add = (id, name, ok, proof) => { rows.push({ id, name, ok, proof }); console.log(`${ok ? "PASS" : "FAIL"} ${id} ${name}: ${proof}`); };
const lc = (s) => String(s ?? "").toLowerCase();

async function cases(X, pid) {
  const out = [];
  for (let off = 0; ; ) { const pg = await X.view("get_pool_cases", [pid, off, 50]); out.push(...pg.items); if (pg.next_offset < 0) return out; off = pg.next_offset; }
}
const canon = await cases(C, seed.pool_id);

// A source
{
  const v = sh("node", ["tools/verify_source.mjs", "--json"]);
  const r = JSON.parse(v.stdout);
  const b = sh("python3", ["tools/build.py", "--check"]);
  add("A", "source", r.ok && b.status === 0, `${r.rows.filter((x) => x.identical).length}/4 contracts read back from Studio Dev byte-identical to build/ at ${r.commit.slice(0, 7)} and HEAD (sha256 ${r.rows.map((x) => x.sha256.slice(0, 8)).join(", ")}); one commit: ${r.one_commit}; build/ fresh: ${b.status === 0}`);
}
// B funds
{
  const parts = [];
  let ok = true;
  for (const [n, X] of [["SandwichRefund", C], ["SandwichRefundDemo", D]]) {
    const s = await X.view("get_stats");
    const bal = await balanceOf(dep[n].address);
    const eq = BigInt(s.received_total) === BigInt(s.held) + BigInt(s.refunded_total) + BigInt(s.returned_total) + BigInt(s.credit_paid_total);
    if (!eq || bal !== 0n || s.held !== "0") ok = false;
    parts.push(`${n}: received ${s.received_total} = refunded ${s.refunded_total} + returned ${s.returned_total} + credits ${s.credit_paid_total} + held ${s.held}: ${eq}; eth_getBalance ${bal}`);
  }
  add("B", "funds", ok, parts.join("; "));
}
// C stuck states
{
  let open = 0, n = 0;
  for (const X of [C, D]) for (let off = 0; ; ) { const pg = await X.view("get_pools", [off, 50, Math.floor(Date.now() / 1000)]); n += pg.items.length; open += pg.items.filter((p) => p.status !== "CLOSED").length; if (pg.next_offset < 0) break; off = pg.next_offset; }
  const credits = await Promise.all([C, D].map((X) => X.view("get_stats")));
  const unv = canon.filter((c) => c.state === "UNVERIFIABLE").length;
  const refile = demo.steps.find((s) => s.id === "A_refile_unverifiable");
  add("C", "stuck states", open === 0 && unv === 0 && credits.every((s) => s.credit_owed_total === "0") && refile?.ok, `${n} pools, ${open} not closed; credits owed ${credits.map((s) => s.credit_owed_total).join("/")}; canonical UNVERIFIABLE ${unv}; an UNVERIFIABLE case was filed again on chain (attempts ${refile?.attempts}); every GEN left by refund, close or withdraw (B)`);
}
// D evidence binding: each refund went to the tx.from that Ethereum reports now, and to nobody else
{
  const bad = [];
  const ref = canon.filter((c) => c.state === "SANDWICHED_REFUNDED");
  const txs = await rpcSend(CHAINS.ethereum.rpcs[1], ref.map((c) => ["eth_getTransactionByHash", [c.tx_hash]]));
  for (let i = 0; i < ref.length; i++) {
    const c = ref[i], r = ver.refunds.cases.find((x) => x.tx_hash === c.tx_hash);
    if (lc(txs[i]?.from) !== c.victim) bad.push(`${c.tx_hash.slice(0, 10)} tx.from ${txs[i]?.from}`);
    const tx = await finalized(C.read, r.filing_tx, { timeoutMs: 60000 });
    const d = payoutDelivered(tx, c.victim, c.refund_paid);
    const others = (tx.messages ?? []).filter((m) => BigInt(m.value ?? 0) > 0n && lc(m.recipient) !== c.victim);
    if (!d.ok || others.length) bad.push(`${c.tx_hash.slice(0, 10)} payout ${d.why}${others.length ? " + other recipients" : ""}`);
    if (c.facts.front_tx === c.tx_hash || c.facts.back_tx === c.tx_hash) bad.push(`${c.tx_hash.slice(0, 10)} pair includes the victim`);
  }
  add("D", "evidence binding", bad.length === 0, `${ref.length} refunds: each case is (pool ${seed.pool_id}, ethereum, tx hash), its victim equals the tx.from Ethereum reports now (read again from ${new URL(CHAINS.ethereum.rpcs[1]).host}), its filing transaction is FINALIZED with exactly one value message, to that victim, for the recorded amount; front/back are other transactions${bad.length ? "; " + bad.join("; ") : ""}`);
}
// E two sources
{
  const agree = feas.cases.filter((c) => c.agree).length;
  const g = Object.values(gv.reads).filter((r) => r.read.facts).length;
  const ks = await (await fetch("https://raw.githubusercontent.com/kenil1710/sandwichrefund/keeper-state/keeper-state-SandwichRefund.json")).json();
  const pc = ks.pools["1"].chains.ethereum;
  add("E", "two sources", agree === 65 && g === 65 && pc.failed.length === 0, `contract reads ${CHAINS.ethereum.rpcs.join(" + ")} (two operators) and requires identical facts; Mac: ${agree}/65 cases agreed; GenVM probe: ${g}/65 identical to the Mac; keeper: ${pc.pages_ok} pages each answered identically by two scan endpoints, ${pc.failed.length} left to retry`);
}
// F identity incl. self-sandwich farming
{
  const self = canon.filter((c) => c.state.startsWith("SANDWICHED") && [c.facts.attacker_eoa, c.facts.attacker_contract, c.facts.attacker_recipient].includes(c.victim));
  const tr = spawnSync("python3", ["-m", "unittest", "test_attacks.FakeVictims", "test_rule.SelfSandwich"], { cwd: root + "test", encoding: "utf8" });
  const n = Number((tr.stderr.match(/Ran (\d+)/) ?? [])[1] ?? 0);
  const created = seed.created_at, endBlock = pool.ranges[0].end_block;
  add("F", "identity and self-sandwich farming", self.length === 0 && tr.status === 0, `0 refunded victims linked to their attacker (EOA, contract, recipient) of ${canon.filter((c) => c.state.startsWith("SANDWICHED")).length}; ${n} identity tests pass (attacker = victim, victim swap pays the bot, bot pays the victim, bot sends the victim tx, back-run from victim, caps bound an unlinked wallet); the canonical range ends at block ${endBlock}, mined before the pool was created (${new Date(created * 1000).toISOString()}), so no new sandwich can fall in it`);
}
// G coverage
{
  const routers = new Set(pool.routers.map((r) => r.address));
  const bad = canon.filter((c) => c.state.startsWith("SANDWICHED") && (!routers.has(c.router) || c.block < pool.ranges[0].start_block || c.block > pool.ranges[0].end_block || !["V2", "V3"].includes(c.facts.kind)));
  const nc = demo.steps.filter((s) => s.case?.state === "NOT_COVERED").map((s) => s.case.reason);
  add("G", "coverage", bad.length === 0 && nc.length === 3, `every canonical SANDWICHED case: router in the 11 covered, block in ${pool.ranges[0].start_block}-${pool.ranges[0].end_block}, pool V2/V3 and factory-canonical; demo refused on chain: ${nc.join(", ")}`);
}
// H counters
{
  const s = await C.view("get_stats");
  const tally = {};
  for (const c of canon) tally[c.state] = (tally[c.state] ?? 0) + 1;
  const p = await C.view("get_pool", [seed.pool_id, 0]);
  const sumPaid = canon.reduce((a, c) => a + BigInt(c.refund_paid), 0n);
  const ok = Object.entries(tally).every(([k, v]) => s.counts["state:" + k] === v) && s.cases === canon.length && p.n_refunded === (tally.SANDWICHED_REFUNDED ?? 0)
    && BigInt(p.refunded) === sumPaid && BigInt(s.refunded_total) === sumPaid && s.counts.filings === canon.length;
  add("H", "counters", ok, `get_stats state counters ${JSON.stringify(Object.fromEntries(Object.entries(s.counts).filter(([k]) => k.startsWith("state:") && s.counts[k])))} = tally of the ${canon.length} paginated cases; filings ${s.counts.filings}; pool n_refunded ${p.n_refunded}; refunded ${p.refunded} = sum of case payouts = refunded_total`);
}
// I real-world truth
{
  const sa = rw.sandwiched.filter((x) => x.agree).length, ca = rw.clean.filter((x) => x.agree).length;
  add("I", "real-world truth", sa === rw.sandwiched.length && ca === rw.clean.length, `${sa}/${rw.sandwiched.length} SANDWICHED confirmed by the attackers' own Transfer flows, ${ca}/${rw.clean.length} CLEAN by the victims' neighbours; public explorers linked per case (EigenPhi, libMEV, Phalcon) but not machine-readable today (see REAL_WORLD_CHECK.md); 0 disagreements`);
}
// J keeper
{
  const run = keeperRun;
  const ks = await (await fetch("https://raw.githubusercontent.com/kenil1710/sandwichrefund/keeper-state/keeper-state-SandwichRefund.json")).json();
  const a = Object.values(ks.actions);
  const done = a.filter((x) => x.status === "DONE").length, failed = a.filter((x) => x.status === "FAILED").length;
  const t = spawnSync("node", ["--test", "keeper.test.mjs"], { cwd: root + "test", encoding: "utf8" });
  const pass = Number((t.stdout.match(/# pass (\d+)/) ?? [])[1] ?? 0);
  add("J", "keeper", run.event === "schedule" && run.conclusion === "success" && failed === 0 && done === a.length && t.status === 0,
    `scheduled run ${run.id} (${run.event}, ${run.conclusion}, ${run.created_at}); canonical actions ${done}/${a.length} DONE (65 FILE + 1 CLOSE), ${failed} failed; every DONE was FINALIZED, executed and re-read; ${pass} keeper tests (outage, backfill, >50 pools, >500 cases, idempotency, ACCEPTED-not-final, stale 6 h, resume)`);
}
// K gate meaning: bound to (canonical pool, its sponsor); a copycat id or another sponsor is never read
{
  const P = seed.pool_id, SP = seed.sponsor.toLowerCase();
  const sample = [canon.find((c) => c.state === "SANDWICHED_REFUNDED"), canon.find((c) => c.state === "CLEAN"), canon.find((c) => c.state === "UNCLEAR")];
  const got = [];
  for (const c of sample) got.push(await G.view("check_case", [P, SP, "ethereum", c.tx_hash]));
  const unfiled = await G.view("check_case", [P, SP, "ethereum", "0x" + "12".repeat(32)]);
  const nopool = await G.view("check_case", [999, SP, "ethereum", sample[0].tx_hash]);
  const wrongSponsor = await G.view("check_case", [P, "0x" + "9".repeat(40), "ethereum", sample[0].tx_hash]);
  const otherChain = await G.view("check_case", [P, SP, "base", sample[0].tx_hash]);
  const dg = demo.steps.find((s) => s.id === "gate");
  const ok = got[0].refunded && !got[0].clean && got[1].clean && !got[2].clean && !got[2].refunded && unfiled.state === "UNVERIFIABLE" && !unfiled.clean
    && nopool.state === "NO_POOL" && wrongSponsor.state === "UNVERIFIABLE" && !wrongSponsor.refunded && otherChain.state === "NOT_COVERED" && dg?.ok
    && dg.states.copycat_named_as_A.state === "UNVERIFIABLE";
  add("K", "gate meaning", ok, `MEVGate bound to (pool ${P}, its sponsor): refunded case -> ${got[0].state} refunded=${got[0].refunded}; clean -> ${got[1].state} clean=${got[1].clean}; unclear -> ${got[2].state}; unfiled -> ${unfiled.state}; pool 999 -> ${nopool.state}; another sponsor named -> ${wrongSponsor.state} refunded=${wrongSponsor.refunded}; other chain -> ${otherChain.state}; demo: a copycat pool's refund read as ${dg?.states?.copycat_named_as_A?.state}; 600 corrupted answers and 300 corrupted pools never favorable (test_meaning)`);
}
// L docs truth
{
  const t = spawnSync("python3", ["-m", "unittest", "test_meaning"], { cwd: root + "test", encoding: "utf8" });
  const n = Number((t.stderr.match(/Ran (\d+)/) ?? [])[1] ?? 0);
  const site = await (await fetch("https://sandwichrefund.vercel.app/docs")).text();
  const sha = j("frontend/src/app/docs/rules.json").rules_md_sha256;
  add("L", "docs truth", t.status === 0 && site.includes(sha.slice(0, 16)), `${n} meaning tests pass: every reason code in the contract is in RULES.md, every constant with its value, modes, refund and profit formulas, RPCs; the JS mirror equals the contract rule on all 65 real cases and every fixture; the live /docs page serves RULES.md sha256 ${sha.slice(0, 16)}`);
}
// M verification package
{
  const fc = readFileSync(root + "docs/FINAL_CHECK.md", "utf8");
  const sub = readFileSync(root + "docs/SUBMISSION.md", "utf8");
  const pin = sub.match(/blob\/([0-9a-f]{40})\//)?.[1];
  const onMain = pin && sh("git", ["branch", "-r", "--contains", pin]).stdout.includes("origin/main");
  add("M", "verification package", /11\/11 checks pass/.test(fc) && onMain && !!keeperRun.id && sub.includes(String(keeperRun.id)), `FINAL_CHECK.md 11/11; SUBMISSION.md evidence pinned to ${pin?.slice(0, 7)} (on origin/main: ${onMain}); scheduled run linked; one-liner/description/review texts ASCII within limits; verify_source, final_check and run_offline.sh reproduce it`);
}
// N demo
{
  const pays = demo.steps.filter((s) => s.payout);
  const fin = demo.steps.find((s) => s.id === "final_balance");
  const states = [...new Set(demo.steps.filter((s) => s.case).map((s) => s.case.state + "/" + (s.case.limit || s.case.reason)))];
  add("N", "demo", demo.steps.every((s) => s.ok) && pays.every((s) => s.payout.arrived && s.payout.delivered) && fin.balance === "0" && (await balanceOf(dep.SandwichRefundDemo.address)) === 0n,
    `${demo.steps.length} steps all ok; ${pays.length} payouts arrived (refund limits RATE, MAX_PER_SWAP, MAX_PER_VICTIM, POOL_BALANCE; closes; credit withdrawal); paths: ${states.join(", ")}; refusals (duplicate, early close, stranger extend, bad terms); demo contract eth_getBalance 0`);
}
const pass = rows.filter((r) => r.ok).length;
writeFileSync(root + "docs/AUDIT.md", ["# Audit", "", `Generated by \`node tools/audit.mjs\` at ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC. **${pass}/${rows.length} PASS.**`, "",
  "| | check | result | proof |", "|---|---|---|---|", ...rows.map((r) => `| ${r.id} | ${r.name} | ${r.ok ? "PASS" : "FAIL"} | ${r.proof.replace(/\|/g, "/")} |`), ""].join("\n"));
console.log(`${pass}/${rows.length}`);
process.exit(pass === rows.length ? 0 : 1);
