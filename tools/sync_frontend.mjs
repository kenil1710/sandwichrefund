// Copies into frontend/src what the site must show exactly as the repository has it:
// deployments.json -> lib/deployments.json, data/{tokens,labels,pool_canonical}.json -> lib/,
// docs/RULES.md -> content/RULES.md (rendered at /docs, with its sha256 in app/docs/rules.json).
// tools/final_check.mjs fails if a copy drifts.
//   node tools/sync_frontend.mjs [--check]
import { readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { createHash } from "node:crypto";
const root = new URL("..", import.meta.url).pathname;
const dep = JSON.parse(readFileSync(root + "deployments.json", "utf8"));
const c = dep.contracts;
const deployments = JSON.stringify({ commit: c.SandwichRefund.commit, network: dep.network, chain_id: dep.chain_id, explorer: dep.explorer,
  registry: c.SandwichRefund.address, registryDemo: c.SandwichRefundDemo.address, gate: c.MEVGate.address, gateDemo: c.MEVGateDemo.address,
  contracts: Object.fromEntries(Object.entries(c).map(([k, v]) => [k, { address: v.address, file: v.file, sha256: v.sha256, bytes: v.bytes, commit: v.commit, deploy_tx: v.deploy_tx, constructor_args: v.constructor_args }])) }, null, 2) + "\n";
const rules = readFileSync(root + "docs/RULES.md", "utf8");
const seed = JSON.parse(readFileSync(root + "docs/seed-canonical.json", "utf8"));
const files = [
  ["frontend/src/lib/deployments.json", deployments],
  ["frontend/src/lib/tokens.json", readFileSync(root + "data/tokens.json", "utf8")],
  ["frontend/src/lib/labels.json", readFileSync(root + "data/labels.json", "utf8")],
  ["frontend/src/lib/pool_canonical.json", readFileSync(root + "data/pool_canonical.json", "utf8")],
  // the (pool id, sponsor) the site's gate reads are bound to
  ["frontend/src/lib/binding.json", JSON.stringify({ pool_id: seed.pool_id, sponsor: seed.sponsor.toLowerCase() }, null, 1) + "\n"],
  ["frontend/src/content/RULES.md", rules],
  ["frontend/src/app/docs/rules.json", JSON.stringify({ rules_md_sha256: createHash("sha256").update(rules).digest("hex") }, null, 1) + "\n"],
];
let stale = 0;
for (const [p, body] of files) {
  if (process.argv.includes("--check")) {
    if (!existsSync(root + p) || readFileSync(root + p, "utf8") !== body) { console.log("STALE " + p); stale++; }
    continue;
  }
  mkdirSync(root + p.slice(0, p.lastIndexOf("/")), { recursive: true });
  writeFileSync(root + p, body);
  console.log("wrote " + p);
}
process.exit(stale ? 1 : 0);
