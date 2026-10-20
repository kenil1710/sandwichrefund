/**
 * Creates test/.accounts.json (gitignored): throwaway Studio Dev signing keys.
 * Existing roles are preserved unless --force is passed. Keys never leave this
 * file; scripts load them and print addresses only.
 *
 *   deployer   deploys every contract
 *   sponsor    funds the canonical pool and the demo pools; receives what is left at close
 *   sponsor2   a second demo sponsor (top-up / close refusals)
 *   keeper     the keeper bot signer (files cases, closes pools)
 *   filer      files demo cases by hand (anyone may)
 *   stranger   anyone else: calls that must be refused
 *   probe      throwaway GenVM probes
 */
import { createAccount } from "genlayer-js";
import { randomBytes } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const target = new URL("./.accounts.json", import.meta.url);
const force = process.argv.includes("--force");
const ROLES = ["deployer", "sponsor", "sponsor2", "keeper", "filer", "stranger", "probe"];
const existing = existsSync(target) && !force ? JSON.parse(readFileSync(target, "utf8")) : {};
const out = {};
for (const role of ROLES) {
  if (existing[role]?.key) { out[role] = existing[role]; continue; }
  const key = `0x${randomBytes(32).toString("hex")}`;
  out[role] = { key, address: createAccount(key).address };
}
writeFileSync(target, JSON.stringify(out, null, 2) + "\n", { mode: 0o600 });
for (const role of ROLES) console.log(`  ${role.padEnd(10)} ${out[role].address}`);
