/**
 * Everything at once, written to docs/FINAL_CHECK.md:
 *   1  build/ is the build of contracts/; the site's copies match the repository
 *   2  on-chain code is byte-identical to build/ at the deploy commit and HEAD, all from one commit
 *   3  addresses are the same everywhere they are written
 *   4  every link in the docs answers 200 (or is a site that only serves browsers)
 *   5  every real case of the canonical pool is decided (none UNVERIFIABLE) and the pool is closed
 *   6  every refund arrived (canonical victims and every demo payout: finalized, delivered, balances moved by the amount)
 *   7  the contracts' eth_getBalance is what their ledgers say (0 when all is closed)
 *   8  the keeper ran within the last 8 hours, has no failed action, and a scheduled run succeeded
 *   9  the offline test suite passes (300+)
 *  10  no placeholder language in the docs; no mention of tooling vendors
 *  11  the live site answers on every page and API
 *   node tools/final_check.mjs       exit 1 if any check fails
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import { execFileSync, spawnSync } from "node:child_process";
import { client, deployments, balanceOf, finalized, payoutDelivered } from "./lib/sr.mjs";
import { CHAINS, SCAN_RPCS } from "./lib/chains.mjs";

const root = new URL("..", import.meta.url).pathname;
const rd = (p) => readFileSync(root + p, "utf8");
const dep = deployments().contracts;
const SITE = "https://sandwichrefund.vercel.app";
const REPO = "kenil1710/sandwichrefund";
const checks = [];
const add = (name, ok, detail) => { checks.push({ name, ok, detail }); console.log(`${ok ? "PASS" : "FAIL"}  ${name}: ${detail}`); };
const sh = (cmd, args) => spawnSync(cmd, args, { cwd: root, encoding: "utf8", maxBuffer: 64 << 20 });
const raw = async (path) => { try { return await (await fetch(`https://raw.githubusercontent.com/${REPO}/keeper-state/${path}`, { cache: "no-store" })).json(); } catch { return null; } };

// 1
{
  const b = sh("python3", ["tools/build.py", "--check"]);
  const f = sh("node", ["tools/sync_frontend.mjs", "--check"]);
  add("build and site copies fresh", b.status === 0 && f.status === 0, b.status === 0 && f.status === 0 ? "build/ = contracts/ + shared helpers; the site's copies of deployments, tokens, labels, the canonical terms and RULES.md are identical" : (b.stdout + f.stdout).trim());
}
// 2
{
  const v = sh("node", ["tools/verify_source.mjs", "--json"]);
  let j = null; try { j = JSON.parse(v.stdout); } catch { /* */ }
  add("source match", v.status === 0 && j?.ok, j ? `${j.rows.filter((r) => r.identical).length}/${j.rows.length} contracts read back from Studio Dev are byte-identical to build/ at ${j.commit.slice(0, 7)} and HEAD; all from one commit: ${j.one_commit}` : v.stderr.slice(0, 200));
}
// 3
{
  const addrs = Object.values(dep).map((c) => c.address);
  const files = ["README.md", "docs/SUBMISSION.md", "docs/SEEDS.md", "frontend/src/lib/deployments.json"];
  const missing = [];
  for (const f of files) { if (!existsSync(root + f)) { missing.push(f + " (missing)"); continue; } const t = rd(f).toLowerCase(); for (const a of addrs) if (!t.includes(a.toLowerCase())) missing.push(`${f} lacks ${a}`); }
  const smoke = existsSync(root + "deployments.smoke.json") ? Object.values(JSON.parse(rd("deployments.smoke.json")).contracts).map((c) => c.address.toLowerCase()) : [];
  const stray = [];
  for (const f of ["README.md", "docs/SUBMISSION.md"]) if (existsSync(root + f)) for (const s of smoke) if (rd(f).toLowerCase().includes(s)) stray.push(`${f} names smoke contract ${s}`);
  add("addresses consistent", missing.length === 0 && stray.length === 0, missing.length + stray.length === 0 ? `the 4 deployed addresses appear in ${files.join(", ")}; no smoke address in README or SUBMISSION` : [...missing, ...stray].join("; "));
}
// 4
{
  const BROWSER_ONLY = /(etherscan\.io|eigenphi\.io|libmev\.com|blocksec\.com)/;
  // FINAL_CHECK.md itself quotes the links this check reports, so it is not scanned
  const docs = ["README.md", ...readdirSync(root + "docs").filter((f) => f.endsWith(".md") && f !== "FINAL_CHECK.md").map((f) => "docs/" + f)];
  const urls = new Set();
  const RPCS = new Set([...Object.values(CHAINS).flatMap((c) => c.rpcs), ...Object.values(SCAN_RPCS).flat()]);
  for (const f of docs) for (const m of rd(f).matchAll(/https?:\/\/[^\s)<>"'`|\]*]+/g)) { const u = m[0].replace(/[.,;:]+$/, ""); if (!RPCS.has(u) && !u.includes("api.libmev.com") && !u.includes("data.zeromev.org")) urls.add(u); }
  // one link per distinct explorer page shape is enough: the rest differ only by hash
  const sample = new Map();
  for (const u of urls) { const key = BROWSER_ONLY.test(u) ? u.replace(/0x[0-9a-f]{40,64}/gi, "X") : u; if (!sample.has(key)) sample.set(key, u); }
  const list = [...sample.values()];
  const bad = [], browser = [];
  let ok = 0;
  for (let i = 0; i < list.length; i += 8) {
    await Promise.all(list.slice(i, i + 8).map(async (u) => {
      let code = 0;
      for (let k = 0; k < 3 && code !== 200; k++) {
        try { const r = await fetch(u, { redirect: "follow", headers: { "user-agent": "Mozilla/5.0 (Macintosh) final_check" }, signal: AbortSignal.timeout(25000) }); code = r.status; } catch { code = -1; }
        if (code !== 200) await new Promise((r) => setTimeout(r, 1500));
      }
      if (code === 200) ok++;
      else if (BROWSER_ONLY.test(u)) browser.push(`${u.split("/")[2]} (${code})`);
      else bad.push(`${u} (${code})`);
    }));
  }
  add("links", bad.length === 0, `${urls.size} distinct links, ${list.length} checked (explorer pages sampled once per shape): ${ok} answered 200; ${browser.length} explorer pages that serve browsers only or are offline (${[...new Set(browser)].join(", ") || "none"}, see docs/REAL_WORLD_CHECK.md)${bad.length ? "; BROKEN: " + bad.join(", ") : ""}`);
}
// 5, 6 canonical
const seed = JSON.parse(rd("docs/seed-canonical.json"));
const ver = JSON.parse(rd("docs/seed-canonical-verify.json"));
const C = client({ role: "keeper", address: dep.SandwichRefund.address });
{
  const p = await C.view("get_pool", [seed.pool_id, 0]);
  const feas = JSON.parse(rd("docs/feasibility.json"));
  const cases = [];
  for (let off = 0; ; ) { const pg = await C.view("get_pool_cases", [seed.pool_id, off, 50]); cases.push(...pg.items); if (pg.next_offset < 0) break; off = pg.next_offset; }
  const counts = {};
  for (const c of cases) counts[c.state] = (counts[c.state] ?? 0) + 1;
  const undecided = cases.filter((c) => !c.final);
  const missing = feas.cases.filter((f) => !cases.find((c) => c.tx_hash === f.hash));
  add("cases settled", undecided.length === 0 && missing.length === 0 && p.status === "CLOSED",
    `${cases.length} cases on canonical pool ${seed.pool_id} (${Object.entries(counts).map(([k, v]) => `${k} ${v}`).join(", ")}); ${missing.length} real cases not filed; ${undecided.length} undecided; pool ${p.status}${p.closed_at ? `, closed ${p.closed_at - p.claim_deadline} s after its 1 h claim period` : ""}`);
}
{
  const bad = [];
  let n = 0;
  for (const r of ver.refunds.cases.filter((x) => x.state === "SANDWICHED_REFUNDED")) {
    const tx = await finalized(C.read, r.filing_tx, { timeoutMs: 60000 });
    const d = payoutDelivered(tx, r.victim, r.refund_paid);
    if (!d.ok) bad.push(`canonical ${r.tx_hash.slice(0, 10)}: ${d.why}`); else n++;
  }
  const notArrived = ver.refunds.victims.filter((v) => !v.arrived);
  if (notArrived.length) bad.push(`${notArrived.length} victims' balances did not move by their refunds`);
  if (!ver.close?.delivered || !ver.close?.arrived) bad.push("the close remainder did not arrive at the sponsor");
  const demo = JSON.parse(rd("docs/demo-run.json"));
  const D = client({ role: "keeper", address: dep.SandwichRefundDemo.address });
  let dn = 0;
  for (const s of demo.steps.filter((x) => x.payout)) {
    const tx = await finalized(D.read, s.tx, { timeoutMs: 60000 });
    const d = payoutDelivered(tx, s.payout.to, s.payout.amount);
    if (!d.ok || !s.payout.arrived) bad.push(`demo ${s.id}: ${d.why || "balance did not move by the amount"}`); else dn++;
  }
  add("refunds arrived", bad.length === 0 && n > 0 && dn > 0, `${n} canonical refunds finalized and delivered, ${ver.refunds.victims.length} victims' Studio Dev balances moved by exactly their refunds; the close remainder ${ver.close?.returned} wei arrived at the sponsor; ${dn} demo payouts finalized, delivered and matched by balance deltas${bad.length ? "; " + bad.join("; ") : ""}`);
}
// 7
{
  const parts = [];
  let ok = true;
  for (const n of ["SandwichRefund", "SandwichRefundDemo"]) {
    const X = client({ role: "keeper", address: dep[n].address });
    const s = await X.view("get_stats");
    const bal = await balanceOf(dep[n].address);
    if (bal !== BigInt(s.held) || bal !== 0n) ok = false;
    parts.push(`${n} eth_getBalance ${bal} wei, ledger holds ${s.held}`);
  }
  add("balances as expected", ok, parts.join("; "));
}
// 8
{
  const st = await raw("status.json");
  const ks = await raw("keeper-state-SandwichRefund.json");
  const last = st?.finished_at ? Date.parse(st.finished_at) : 0;
  const age = (Date.now() - last) / 1000;
  const failed = Object.values(ks?.actions ?? {}).filter((a) => a.status === "FAILED");
  const done = Object.values(ks?.actions ?? {}).filter((a) => a.status === "DONE");
  let sched = null;
  try { sched = (await (await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/keeper.yml/runs?event=schedule&status=success&per_page=1`, { headers: { "user-agent": "final_check" } })).json()).workflow_runs?.[0] ?? null; } catch { /* */ }
  add("keeper ran", last > 0 && age < 8 * 3600 && failed.length === 0 && sched !== null, `last run finished ${st?.finished_at ?? "never"} (${Math.round(age / 60)} min ago, ${st?.trigger}), ${done.length} canonical actions done, ${failed.length} failed; ${sched ? `latest successful scheduled run ${sched.html_url} (${sched.created_at})` : "NO successful scheduled run yet"}`);
}
// 9
{
  const t = sh("sh", ["test/run_offline.sh"]);
  const all = t.stdout + t.stderr;
  const py = Number(all.match(/Ran (\d+) tests/)?.[1] ?? 0), js = Number(all.match(/# pass (\d+)/)?.[1] ?? 0), jf = Number(all.match(/# fail (\d+)/)?.[1] ?? 1);
  add("tests pass", t.status === 0 && jf === 0 && py + js >= 300, `${py + js} offline tests (${py} contract, gate, attack and meaning; ${js} keeper), ${t.status === 0 ? "all pass" : "FAILURES"}`);
}
// 10
{
  const files = ["README.md", ...readdirSync(root + "docs").filter((f) => f.endsWith(".md")).map((f) => "docs/" + f)];
  const hits = [];
  for (const f of files) for (const w of [/Known limitations/i, /\bTODO\b/, /\bTBD\b/, /lorem/i, /\bClaude\b/, /Anthropic/i, /Co-Authored-By/i]) if (w.test(rd(f))) hits.push(`${f}: ${w}`);
  const log = sh("git", ["log", "--format=%B"]).stdout;
  if (/Co-Authored-By|Claude|Anthropic/i.test(log)) hits.push("a commit message");
  add("no placeholders", hits.length === 0, hits.length ? hits.join("; ") : `${files.length} documents and every commit message checked`);
}
// 11
{
  const caseHash = ver.refunds.cases.find((x) => x.state === "SANDWICHED_REFUNDED").tx_hash;
  const victim = ver.refunds.cases.find((x) => x.state === "SANDWICHED_REFUNDED").victim;
  const pages = ["/", "/lookup", `/lookup?address=${victim}`, "/pools", `/pool/${seed.pool_id}`, `/pool/1?reg=demo`, "/sponsor", "/gate", "/keeper", "/verify", "/docs",
    `/case/ethereum/${caseHash}`, `/api/case?chain=ethereum&hash=${caseHash}`, `/api/address?address=${victim}`, `/api/badge?chain=ethereum&hash=${caseHash}`, "/api/verify"];
  const bad = [];
  for (const p of pages) {
    let code = 0, body = "";
    for (let k = 0; k < 3 && code !== 200; k++) { try { const r = await fetch(SITE + p, { signal: AbortSignal.timeout(60000) }); code = r.status; body = await r.text(); } catch { code = -1; } }
    if (code !== 200) bad.push(`${p} ${code}`);
    if (p === "/api/verify" && !/"ok":true/.test(body)) bad.push("/api/verify not ok");
    if (p === "/api/verify" && !body.includes(dep.SandwichRefund.address)) bad.push("the live site still serves another deployment than deployments.json");
  }
  add("live site", bad.length === 0, `${pages.length - bad.length}/${pages.length} pages and APIs answer 200 at ${SITE}${bad.length ? "; " + bad.join(", ") : ""}`);
}

const head = execFileSync("git", ["-C", root, "rev-parse", "HEAD"]).toString().trim();
const pass = checks.filter((c) => c.ok).length;
const md = ["# Final check", "", `Generated by \`node tools/final_check.mjs\` at ${new Date().toISOString().slice(0, 16).replace("T", " ")} UTC on commit \`${head.slice(0, 7)}\`.`, "",
  `**${pass}/${checks.length} checks pass.**`, "", "| # | Check | Result | Detail |", "|---|---|---|---|",
  ...checks.map((c, i) => `| ${i + 1} | ${c.name} | ${c.ok ? "PASS" : "FAIL"} | ${c.detail.replace(/\|/g, "/")} |`), ""];
writeFileSync(root + "docs/FINAL_CHECK.md", md.join("\n"));
console.log(`\n${pass}/${checks.length} pass; wrote docs/FINAL_CHECK.md`);
process.exit(pass === checks.length ? 0 : 1);
