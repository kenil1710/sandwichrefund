/**
 * The keeper bot (GitHub Actions, hourly and 6-hourly; runnable by hand).
 * For every pool of the canonical SandwichRefund in deployments.json: scans
 * the covered routers' swaps in the pool's block range, files every candidate
 * victim (and every data/cases.json hash in the range); on both contracts
 * (canonical and demo, whose cases the demo script files itself) closes every
 * pool past its claim deadline. Logic: tools/lib/keeper_core.mjs.
 *
 *   node tools/keeper.mjs --state=<dir> [--push] [--max=25] [--wait=300] [--settle=900] [--pages=400]
 *
 * --wait: per filing, how long to wait for ACCEPTED before the next one (Studio
 * holds one transaction slot per contract); --settle: at the end, how long to
 * poll this run's transactions until FINALIZED (the rest is resumed next run).
 *
 * State lives in <dir>/keeper-state-<Contract>.json: in CI <dir> is a worktree
 * of the `keeper-state` branch and every checkpoint is committed there (and
 * pushed with --push), so a run that dies resumes from its stored transaction
 * hashes and page cursors. <dir>/status.json is what the site's /keeper page
 * shows. The signer is SANDWICH_KEEPER_KEY (CI secret) or the keeper role in
 * test/.accounts.json.
 */
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";
import { CHAINS, accounts, fundOnStudio, outcomeOf, retry, argOf, sleep } from "../test/harness.mjs";
import { manualPayoutFees } from "./lib/sr.mjs";
import { runKeeper, emptyState, totals } from "./lib/keeper_core.mjs";
import { SCAN_RPCS, SWAP_V2, SWAP_V3 } from "./lib/chains.mjs";
import { rpcSend } from "./lib/sandwich.mjs";

const { createClient, createAccount } = createRequire(new URL("../test/package.json", import.meta.url))("genlayer-js");
const root = new URL("..", import.meta.url).pathname;
const dir = argOf("state", root + "state").replace(/\/$/, "");
const push = process.argv.includes("--push");
mkdirSync(dir, { recursive: true });
const dep = JSON.parse(readFileSync(root + "deployments.json", "utf8")).contracts;
const names = ["SandwichRefund", "SandwichRefundDemo"].filter((n) => dep[n]);
const watchAll = JSON.parse(readFileSync(root + "data/cases.json", "utf8")).cases.map((c) => ({ chain: c.chain, hash: c.hash }));

const chainDef = CHAINS.studiodev;
const key = accounts().keeper?.key;
if (!key) { console.error("no keeper key (SANDWICH_KEEPER_KEY or test/.accounts.json)"); process.exit(1); }
const account = createAccount(key);
const wallet = createClient({ chain: chainDef, account });
const read = createClient({ chain: chainDef });
await fundOnStudio(chainDef, account.address, 50n * 10n ** 18n);
const plain = (v) => JSON.parse(JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x.toString() : x instanceof Map ? Object.fromEntries(x) : x)));
const asObj = (v) => plain(typeof v === "string" ? JSON.parse(v) : v);

const git = (...a) => execFileSync("git", ["-C", dir, ...a], { stdio: ["ignore", "pipe", "pipe"] }).toString();
const isRepo = existsSync(dir + "/.git");
let lastPush = 0;
function commit(files, why, force = false) {
  if (!isRepo) return;
  try {
    git("add", ...files);
    if (git("status", "--porcelain").trim() === "") return;
    git("-c", "user.name=sandwichrefund-keeper", "-c", "user.email=keeper@users.noreply.github.com", "commit", "-qm", "keeper: " + why);
    if (push && (force || why.startsWith("submitted") || Date.now() - lastPush > 30_000)) { git("push", "-q", "origin", "HEAD:keeper-state"); lastPush = Date.now(); }
  } catch (e) { console.log("  state commit/push failed: " + String(e.message).slice(0, 160)); }
}

const scan = {
  endpoints: (chain) => SCAN_RPCS[chain],
  async head(u) { const [b] = await rpcSend(u, [["eth_getBlockByNumber", ["finalized", false]]], { tries: 2 }); return Number(BigInt(b.number)); },
  async getLogs(u, chain, from, to) {
    const [logs] = await rpcSend(u, [["eth_getLogs", [{ fromBlock: "0x" + from.toString(16), toBlock: "0x" + to.toString(16), topics: [[SWAP_V2, SWAP_V3]] }]]], { tries: 3 });
    if (!Array.isArray(logs)) throw new Error("no logs array");
    return logs;
  },
  async getTxs(u, chain, hashes) { return rpcSend(u, hashes.map((h) => ["eth_getTransactionByHash", [h]]), { tries: 3 }); },
};

function regFor(address) {
  const view = async (fn, args) => asObj(await retry(() => read.readContract({ address, functionName: fn, args }), { label: fn }));
  async function getTx(hash) {
    const tx = await retry(() => read.getTransaction({ hash }), { attempts: 4, label: "poll" }).catch(() => null);
    if (!tx) return null;
    const o = outcomeOf(tx);
    return { statusName: o.status, ok: o.ok, reason: o.revertReason };
  }
  return {
    now: () => Math.floor(Date.now() / 1000),
    getPools: (off, lim) => view("get_pools", [off, lim, Math.floor(Date.now() / 1000)]),
    getPool: (pid) => view("get_pool", [pid, Math.floor(Date.now() / 1000)]),
    getPoolCase: (pid, chain, hash) => view("get_pool_case", [pid, chain, hash]),
    async fileCase(pid, chain, hash, victim) {
      const fees = await manualPayoutFees(wallet, victim);
      return retry(() => wallet.writeContract({ address, functionName: "file_case", args: [pid, chain, hash], value: 0n, fees }), { label: "file_case" });
    },
    async closePool(pid, sponsor) {
      const fees = await manualPayoutFees(wallet, sponsor);
      return retry(() => wallet.writeContract({ address, functionName: "close_pool", args: [pid], value: 0n, fees }), { label: "close_pool" });
    },
    getTx,
    sleep,
    async wait(hash, ms) {
      const t0 = Date.now();
      for (;;) {
        const tx = await getTx(hash);
        if (tx && ["ACCEPTED", "FINALIZED", "UNDETERMINED", "CANCELED", "LEADER_TIMEOUT", "VALIDATORS_TIMEOUT"].includes(tx.statusName)) return tx;
        if (Date.now() - t0 > ms) return tx;
        await sleep(15_000);
      }
    },
  };
}

const status = { keeper: account.address, started_at: new Date().toISOString(), contracts: {} };
for (const name of names) {
  const address = dep[name].address;
  const file = `${dir}/keeper-state-${name}.json`;
  const store = {
    async load() { return existsSync(file) ? JSON.parse(readFileSync(file, "utf8")) : emptyState(); },
    async save(state, why) {
      state.contract = name; state.address = address; state.keeper = account.address; state.saved_at = new Date().toISOString();
      writeFileSync(file, JSON.stringify(state, null, 1) + "\n");
      commit([file.slice(dir.length + 1)], `${name} ${why}`, why === "run finished");
    },
  };
  console.log(`keeper ${account.address}  ${name} ${address}  state ${file}${isRepo ? " (git)" : ""}`);
  const { run, state } = await runKeeper({ scan, reg: regFor(address), store, watch: name === "SandwichRefund" ? watchAll : [],
    scanPools: name === "SandwichRefund",
    log: (l) => console.log("  " + l), maxActions: Number(argOf("max", "25")), maxPages: Number(argOf("pages", "400")),
    waitMs: Number(argOf("wait", "300")) * 1000, settleMs: Number(argOf("settle", "900")) * 1000 });
  console.log(`  run: resumed ${run.resumed}, pools ${run.pools}, pages ${run.pages} (failed ${run.pages_failed}), candidates ${run.candidates}, submitted ${run.submitted}, done ${run.done}, already ${run.already}, pending ${run.pending}, retry ${run.retry}, failed ${run.failed}`);
  for (const u of state.unprocessed) console.log(`  unprocessed ${u.key}: ${u.why}`);
  status.contracts[name] = { address, last_run: run, totals: totals(state), pools: state.pools, unprocessed: state.unprocessed,
    actions: Object.values(state.actions).map((a) => ({ key: a.key, kind: a.kind, pool_id: a.pool_id, hash: a.hash, status: a.status, result: a.result ?? "",
      tx: a.tx ?? a.tx_history?.at(-1) ?? "", attempts: a.attempts, last_error: a.last_error ?? "", why: a.why ?? "" })) };
}
status.finished_at = new Date().toISOString();
status.trigger = process.env.GITHUB_EVENT_NAME ?? "manual";
status.run_url = process.env.GITHUB_RUN_ID ? `https://github.com/${process.env.GITHUB_REPOSITORY}/actions/runs/${process.env.GITHUB_RUN_ID}` : "";
let hist = [];
try { hist = JSON.parse(readFileSync(`${dir}/status.json`, "utf8")).history ?? []; } catch { /* first run */ }
status.history = [...hist, { started_at: status.started_at, finished_at: status.finished_at, trigger: status.trigger, run_url: status.run_url,
  runs: Object.fromEntries(Object.entries(status.contracts).map(([n, c]) => [n, { submitted: c.last_run.submitted, done: c.last_run.done, pages: c.last_run.pages, pages_failed: c.last_run.pages_failed }])) }].slice(-100);
writeFileSync(`${dir}/status.json`, JSON.stringify(status, null, 1) + "\n");
commit(["status.json"], "status", true);
