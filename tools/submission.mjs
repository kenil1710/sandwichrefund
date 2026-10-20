// docs/SUBMISSION.md: the three submission texts, plain ASCII, each with its length checked against its limit,
// counts read from the evidence files. Evidence links are pinned to one commit.
//   node tools/submission.mjs --tests=<n> --commit=<commit> [--schedule-run=<url>]
import { readFileSync, writeFileSync } from "node:fs";
const root = new URL("..", import.meta.url).pathname;
const j = (p) => JSON.parse(readFileSync(root + p, "utf8"));
const dep = j("deployments.json").contracts;
const ver = j("docs/seed-canonical-verify.json");
const feas = j("docs/feasibility.json");
const rw = j("docs/real_world.json");
const demo = j("docs/demo-run.json");
const arg = (k) => process.argv.find((a) => a.startsWith(`--${k}=`))?.slice(k.length + 3);
const tests = arg("tests") ?? "?";
const commit = arg("commit");
if (!/^[0-9a-f]{40}$/.test(commit ?? "")) { console.error("--commit=<40-hex commit> required"); process.exit(1); }
const deployCommit = dep.SandwichRefund.commit;
const scheduleRun = arg("schedule-run");
const REPO = "https://github.com/kenil1710/sandwichrefund";
const pin = (p) => `${REPO}/blob/${commit}/${p}`;
const R = dep.SandwichRefund.address, RD = dep.SandwichRefundDemo.address, G = dep.MEVGate.address, GD = dep.MEVGateDemo.address;
const n = (v) => feas.cases.filter((c) => c.verdict === v).length;
const c = ver.refunds.counts;
const refunded = c.SANDWICHED_REFUNDED ?? 0;
const gen = (w) => (Number(BigInt(w)) / 1e18).toFixed(3);
const payouts = demo.steps.filter((s) => s.payout).length;

const one = "SandwichRefund: a sponsor funds a pool; GenLayer validators read Ethereum swaps from two RPCs, code detects same-block sandwiches and refunds the victim's loss in GEN.";
const desc = `Wallets and DEX front-ends route users into sandwich attacks and cannot prove or repay the loss. SandwichRefund lets a sponsor lock GEN in a pool with frozen terms: covered routers, Uniswap V2/V3 pools, block range, refund rate per profit token, caps, claim period. Anyone files a victim tx; every validator reads its receipt and the pool's Swap logs from two Ethereum RPCs and code decides: one actor's front-run and back-run on the victim's pool in the same block with positive profit is SANDWICHED and the attacker's net profit is refunded to tx.from at once. Partial patterns are UNCLEAR, never paid. Seeded with ${feas.cases.length} real swaps of 2026-10-20: ${n("SANDWICHED")} sandwiched (jaredfromsubway and ${new Set(feas.cases.filter((x) => x.verdict === "SANDWICHED").map((x) => x.attacker_eoa)).size - 1} other bots), ${n("CLEAN")} clean, ${n("UNCLEAR")} unclear; ${refunded} refunds arrived. MEVGate answers consumers; a keeper scans and files.`;
const rev = `Live: sandwichrefund.vercel.app (/verify: on-chain code vs GitHub). Studio Dev: SandwichRefund ${R}, demo ${RD}, MEVGate ${G}, demo ${GD}. Repo github.com/kenil1710/sandwichrefund: sh test/run_offline.sh (${tests} tests), node tools/verify_source.mjs, node tools/final_check.mjs. Deploy commit ${deployCommit.slice(0, 7)}. docs/SEEDS.md proves ${refunded} canonical and ${payouts} demo payouts.`;

const ascii = (s) => /^[\x20-\x7e]*$/.test(s);
const rows = [["One-liner", one, 180], ["Description", desc, 1000], ["Review verification", rev, 500]];
for (const [nm, t, max] of rows) if (t.length > max || !ascii(t)) { console.error(`${nm}: ${t.length}/${max} chars, ascii ${ascii(t)}`); process.exit(1); }
const md = ["# Submission", "", "Plain ASCII. Lengths checked by `node tools/submission.mjs`.", "",
  ...rows.flatMap(([nm, t, max]) => [`## ${nm} (${t.length}/${max} characters)`, "", t, ""]),
  "## Counts", "",
  `- Real cases: ${feas.cases.length} (SANDWICHED ${n("SANDWICHED")}, CLEAN ${n("CLEAN")}, UNCLEAR ${n("UNCLEAR")}), read from two Ethereum RPCs on a Mac and inside GenVM, identical.`,
  `- Canonical pool: ${Object.entries(c).map(([k, v]) => `${k} ${v}`).join(", ")}; ${gen(ver.refunds.pool.refunded)} GEN refunded, ${gen(ver.close?.returned ?? "0")} GEN returned to the sponsor at close.`,
  `- Real-world check: ${rw.sandwiched.filter((x) => x.agree).length}/${rw.sandwiched.length} SANDWICHED and ${rw.clean.filter((x) => x.agree).length}/${rw.clean.length} CLEAN confirmed.`,
  `- Demo: ${demo.steps.length} steps, ${payouts} payouts, all arrived; demo contract balance at the end ${demo.steps.find((s) => s.id === "final_balance")?.balance} wei.`,
  `- Offline tests: ${tests}.`, "",
  "## Evidence (pinned)", "",
  `Commit \`${commit}\`; contracts deployed from \`${deployCommit}\`.`, "",
  `- Seeds, every refund and its arrival: ${pin("docs/SEEDS.md")}`,
  `- Final check: ${pin("docs/FINAL_CHECK.md")}`,
  `- Real-world check: ${pin("docs/REAL_WORLD_CHECK.md")}`,
  `- Feasibility: ${pin("docs/FEASIBILITY.md")}`,
  `- Rules: ${pin("docs/RULES.md")}`,
  `- Attack round: ${pin("docs/ATTACK_REPORT.md")}`,
  `- Deployed source: ${pin("build/SandwichRefund.py")}, ${pin("build/MEVGate.py")}, ${pin("deployments.json")}`,
  ...(scheduleRun ? [`- Keeper, a scheduled run: ${scheduleRun}`] : []),
  `- Live source check: https://sandwichrefund.vercel.app/verify`, "",
  "## Addresses", "", `- SandwichRefund: ${R}`, `- SandwichRefundDemo: ${RD}`, `- MEVGate: ${G}`, `- MEVGateDemo: ${GD}`, ""];
writeFileSync(root + "docs/SUBMISSION.md", md.join("\n"));
for (const [nm, t, max] of rows) console.log(`${nm}: ${t.length}/${max}`);
