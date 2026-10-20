/**
 * Reads each deployed contract's code BACK FROM STUDIO DEV (gen_getContractCode)
 * and compares it byte for byte with the build file at the deploy commit and
 * at HEAD, and with the sha256 in deployments.json. Also checks every
 * deployment came from the same commit and that contracts/ and build/ did not
 * change after it.
 *   node tools/verify_source.mjs [--json]      exit 1 on any mismatch
 */
import { readFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
const root = new URL("..", import.meta.url).pathname;
const require = createRequire(new URL("../test/package.json", import.meta.url));
const { createClient } = require("genlayer-js");
const { studioDevnet } = require("genlayer-js/chains");
const sha = (b) => createHash("sha256").update(b).digest("hex");
const dep = JSON.parse(readFileSync(root + "deployments.json", "utf8")).contracts;
const git = (...a) => execFileSync("git", ["-C", root, ...a]).toString().trim();
const head = git("rev-parse", "HEAD");
const client = createClient({ chain: studioDevnet });
const json = process.argv.includes("--json");
let bad = 0;
const rows = [];
if (!json) console.log(`HEAD ${head}`);
const commits = new Set(Object.values(dep).map((r) => r.commit));
for (const [name, rec] of Object.entries(dep)) {
  let code = "";
  for (let i = 0; i < 5 && !code; i++) { try { code = await client.getContractCode(rec.address); } catch { await new Promise((r) => setTimeout(r, 3000)); } }
  const atDeploy = execFileSync("git", ["-C", root, "show", `${rec.commit}:${rec.file}`]);
  const atHead = execFileSync("git", ["-C", root, "show", `HEAD:${rec.file}`]);
  const onChain = Buffer.from(String(code), "utf8");
  const same = onChain.equals(atDeploy) && onChain.equals(atHead), recorded = rec.sha256 === sha(atDeploy);
  const touched = git("log", "--format=%h", `${rec.commit}..HEAD`, "--", "contracts", "build");
  if (!same || !recorded || touched !== "") bad++;
  rows.push({ name, address: rec.address, bytes: onChain.length, sha256: sha(onChain), identical: same, recorded, unchanged_since: touched === "" });
  if (!json) console.log(`${name.padEnd(20)} ${rec.address}  ${onChain.length} bytes  sha256 ${sha(onChain).slice(0, 16)}  ${same ? "identical to build file at deploy commit and HEAD" : "DIFFERS"}  ${recorded ? "matches deployments.json" : "MISMATCH"}  ${touched === "" ? "contracts/ and build/ unchanged since" : "CHANGED since: " + touched.split("\n").join(",")}`);
}
if (commits.size !== 1) { bad++; if (!json) console.log("deployments come from more than one commit:", [...commits]); }
else if (!json) console.log(`all deployments from one commit: ${[...commits][0]}`);
if (json) console.log(JSON.stringify({ head, commit: [...commits][0], one_commit: commits.size === 1, ok: bad === 0, rows }, null, 2));
process.exit(bad ? 1 : 0);
