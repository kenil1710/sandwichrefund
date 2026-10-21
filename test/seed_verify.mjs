/**
 * Verifies the canonical seed on chain (docs/seed-canonical.json):
 *
 *   --phase=refunds  every real case filed by the keeper is decided; every
 *                    SANDWICHED_REFUNDED refund ARRIVED: its filing transaction
 *                    is FINALIZED with the value message to the victim
 *                    delivered, and each victim's Studio Dev balance moved by
 *                    exactly the sum of its refunds since the baseline taken
 *                    before the pool existed. Records the sponsor's balance.
 *   --phase=close    the pool is CLOSED after its claim period; the close
 *                    transaction delivered the remainder to the sponsor and the
 *                    sponsor's balance moved by exactly that.
 * Writes docs/seed-canonical-verify.json.
 *   node seed_verify.mjs --phase=refunds|close [--state=<keeper-state dir>]
 */
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { client, deployments, balanceOf, finalized, payoutDelivered, plain } from "../tools/lib/sr.mjs";
import { argOf } from "./harness.mjs";

const phase = argOf("phase", "refunds");
const seed = JSON.parse(readFileSync(new URL("../docs/seed-canonical.json", import.meta.url)));
const OUT = new URL("../docs/seed-canonical-verify.json", import.meta.url);
const doc = existsSync(OUT) ? JSON.parse(readFileSync(OUT)) : {};
const dep = deployments().contracts;
const c = client({ role: "keeper", address: dep.SandwichRefund.address });
const pid = seed.pool_id;

async function keeperActions() {
  const dir = argOf("state", "");
  if (dir) return Object.values(JSON.parse(readFileSync(dir + "/keeper-state-SandwichRefund.json", "utf8")).actions);
  const r = await fetch("https://raw.githubusercontent.com/kenil1710/sandwichrefund/keeper-state/keeper-state-SandwichRefund.json");
  return Object.values((await r.json()).actions);
}

async function allCases() {
  const out = [];
  for (let off = 0; ; ) {
    const pg = await c.view("get_pool_cases", [pid, off, 50]);
    out.push(...pg.items);
    if (pg.next_offset < 0) return out;
    off = pg.next_offset;
  }
}

if (phase === "refunds") {
  const feas = JSON.parse(readFileSync(new URL("../docs/feasibility.json", import.meta.url)));
  const cases = await allCases();
  const actions = await keeperActions();
  const txOf = Object.fromEntries(actions.filter((a) => a.kind === "FILE").map((a) => [a.hash, a]));
  const byVictim = {};
  const rows = [];
  for (const x of cases) {
    const a = txOf[x.tx_hash];
    const row = { case_id: x.case_id, tx_hash: x.tx_hash, state: x.state, reason: x.reason, victim: x.victim, refund_paid: x.refund_paid, limit: x.limit,
      loss: x.loss, filing_tx: a?.tx ?? "", keeper_status: a?.status ?? "", found_by: a?.why ?? "",
      expected: feas.cases.find((f) => f.hash === x.tx_hash)?.verdict ?? "" };
    if (x.state === "SANDWICHED_REFUNDED") {
      const tx = await finalized(c.read, a.tx, { timeoutMs: 300_000 });
      const d = payoutDelivered(tx, x.victim, x.refund_paid);
      row.finalized = tx?.statusName; row.delivered = d.ok; row.why = d.why;
      byVictim[x.victim] = (byVictim[x.victim] ?? 0n) + BigInt(x.refund_paid);
    }
    row.matches_feasibility = row.expected === "" || (row.expected === "SANDWICHED" ? x.state.startsWith("SANDWICHED") : row.expected === x.state);
    rows.push(row);
    console.log(x.case_id, x.tx_hash.slice(0, 10), x.state.padEnd(20), x.refund_paid, row.delivered ?? "", row.matches_feasibility ? "" : "MISMATCH " + row.expected);
  }
  // payouts other runs made to the same victims since the baseline (the e2e run on the demo contract), netted out
  const other = {};
  try {
    const e2e = JSON.parse(readFileSync(new URL("../docs/e2e/summary.json", import.meta.url)));
    const r = e2e.steps.find((x) => x.step === "refund_arrived");
    if (r && Date.parse(e2e.steps[0].at) > Date.parse(seed.at)) other[e2e.victim.toLowerCase()] = (other[e2e.victim.toLowerCase()] ?? 0n) + BigInt(r.refund_paid);
  } catch { /* no e2e run */ }
  const victims = [];
  for (const [v, sum] of Object.entries(byVictim)) {
    const now = await balanceOf(v);
    const base = BigInt(seed.victims_baseline[v] ?? "0");
    const ext = other[v] ?? 0n;
    victims.push({ victim: v, refunds: String(sum), baseline: String(base), balance: String(now), delta: String(now - base),
      other_runs: String(ext), arrived: now - base - ext === sum });
    console.log("victim", v, "refunds", sum, "delta", now - base, "other runs", ext, now - base - ext === sum ? "ARRIVED" : "MISMATCH");
  }
  const p = await c.view("get_pool", [pid, 0]);
  const counts = {};
  for (const r of rows) counts[r.state] = (counts[r.state] ?? 0) + 1;
  doc.refunds = { at: new Date().toISOString(), pool: { status: p.status, funded: p.funded, refunded: p.refunded, balance: p.balance, n_cases: p.n_cases,
    n_refunded: p.n_refunded, n_unpaid: p.n_unpaid, claim_deadline: p.claim_deadline }, counts, cases: rows, victims,
    every_case_decided: rows.length === feas.cases.length && rows.every((r) => r.state !== "UNVERIFIABLE"),
    every_refund_arrived: victims.every((v) => v.arrived) && rows.filter((r) => r.state === "SANDWICHED_REFUNDED").every((r) => r.delivered),
    all_match_feasibility: rows.every((r) => r.matches_feasibility),
    sponsor_balance: String(await balanceOf(seed.sponsor)) };
  writeFileSync(OUT, JSON.stringify(doc, null, 1) + "\n");
  console.log(JSON.stringify({ counts, decided: doc.refunds.every_case_decided, arrived: doc.refunds.every_refund_arrived, match: doc.refunds.all_match_feasibility }));
} else {
  const p = await c.view("get_pool", [pid, 0]);
  const actions = await keeperActions();
  const close = actions.find((a) => a.kind === "CLOSE" && a.pool_id === pid);
  const tx = close?.tx ? await finalized(c.read, close.tx, { timeoutMs: 300_000 }) : null;
  const d = tx ? payoutDelivered(tx, seed.sponsor, p.returned) : { ok: false, why: "no close tx" };
  const now = await balanceOf(seed.sponsor);
  // the sponsor sent one transaction (create_pool) and received only the close: its balance before the close is the
  // pre-seed balance minus the pool and that transaction's net fee (top-ups minus refunds in its fee accounting)
  const ctx = plain(await c.read.getTransaction({ hash: seed.create_tx }));
  const fa = ctx.data?.fee_accounting ?? {};
  const createFee = (fa.top_ups ?? []).reduce((x, t) => x + BigInt(t.amount), 0n) - (fa.refunds ?? []).reduce((x, t) => x + BigInt(t.amount), 0n);
  const before = BigInt(seed.sponsor_balance_before) - BigInt(seed.value) - createFee;
  const contract = await balanceOf(dep.SandwichRefund.address);
  doc.close = { at: new Date().toISOString(), status: p.status, closed_at: p.closed_at, closed_by: p.closed_by, close_tx: close?.tx ?? "", close_status: tx?.statusName ?? "",
    keeper_status: close?.status ?? "", returned: p.returned, refunded: p.refunded, funded: p.funded, delivered: d.ok, why: d.why,
    sponsor_delta: String(now - before), create_fee: String(createFee), arrived: now - before === BigInt(p.returned), adds_up: BigInt(p.refunded) + BigInt(p.returned) === BigInt(p.funded),
    after_deadline_s: p.closed_at - p.claim_deadline, contract_balance: String(contract) };
  writeFileSync(OUT, JSON.stringify(doc, null, 1) + "\n");
  console.log(JSON.stringify(plain(doc.close)));
}
