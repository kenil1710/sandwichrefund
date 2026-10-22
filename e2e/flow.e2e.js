// End to end on the live site, demo contract: a throwaway wallet creates a pool (a refused one first), files a real
// sandwiched Ethereum swap and sees the refund arrive at the victim, has a duplicate filing refused, and closes the
// pool after its claim period, its GEN coming back. Screenshots, video, trace and a summary go to docs/e2e/.
import { test, expect } from "@playwright/test";
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { throwawayWallet, rpc } from "./wallet.js";

const root = new URL("../", import.meta.url);
const dep = JSON.parse(readFileSync(new URL("frontend/src/lib/deployments.json", root)));
const feas = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const DEMO = dep.registryDemo;
const CASE = feas.cases.find((c) => c.hash.startsWith("0xa3bacdd6"));
const SHOTS = new URL("docs/e2e/", root);
mkdirSync(SHOTS, { recursive: true });
const summary = { site: "", demo_contract: DEMO, case: CASE.hash, victim: CASE.victim, steps: [] };
const log = (step, detail) => { summary.steps.push({ step, ...detail, at: new Date().toISOString() }); console.log(step, JSON.stringify(detail)); };
const balance = async (a) => BigInt(await rpc("eth_getBalance", [a, "latest"]));

async function view(page, fn, args) {
  for (let i = 0; i < 6; i++) {
    const r = await page.request.get(`/api/view?a=${DEMO}&f=${fn}&args=${encodeURIComponent(JSON.stringify(args))}&fresh=${Date.now()}`);
    if (r.ok()) return (await r.json()).value;
    await new Promise((s) => setTimeout(s, 5000 * (i + 1)));
  }
  throw new Error("view " + fn);
}
const shot = (page, name) => page.screenshot({ path: new URL(name + ".png", SHOTS).pathname, fullPage: true });
const statusText = (page) => page.getByRole("status").last();

test("sponsor, file, refund, rejected, close on the demo contract", async ({ page, baseURL }) => {
  summary.site = baseURL;
  const w = await throwawayWallet(page);
  log("wallet", { address: w.address, note: "throwaway key for this run, saved in test/.accounts.json before use, funded from the Studio Dev faucet" });

  // 1. connect
  await page.goto("/sponsor");
  await page.getByRole("button", { name: "Connect wallet" }).click();
  await expect(page.getByText(w.address.slice(0, 6))).toBeVisible();
  await shot(page, "01-connected");

  // 2. a refused pool: bad claim period -> rejected, the GEN credited back
  await expect(page.locator("select").first()).toHaveValue("demo");
  await page.getByLabel("Name", { exact: true }).fill("e2e refused pool");
  await page.getByLabel("Claim period (seconds)").fill("5");
  await page.getByLabel("Pool (GEN sent now)").fill("0.001");
  await page.getByRole("button", { name: "Create pool and lock GEN" }).click();
  await expect(statusText(page)).toContainText(/rejected/i, { timeout: 15 * 60_000 });
  await expect(statusText(page)).toContainText("BAD_CLAIM_PERIOD");
  await shot(page, "02-rejected-create");
  log("rejected_create", { status: await statusText(page).innerText() });

  // 2b. withdraw the credit: the throwaway key dies with this run, so nothing may stay owed to it
  const creditBefore = await balance(w.address);
  // the page reads the wallet's credit again once the create settles; no reload (that would drop the wallet)
  await page.getByRole("button", { name: "Withdraw credit (demo)" }).click({ timeout: 300_000 });
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 15 * 60_000 });
  let credit = "1";
  for (let i = 0; i < 30 && credit !== "0"; i++) { credit = (await view(page, "get_credit", [w.address])).credit; if (credit !== "0") await new Promise((s) => setTimeout(s, 10000)); }
  expect(credit).toBe("0");
  log("credit_withdrawn", { credit_left: credit, wallet_delta_after_fee: String((await balance(w.address)) - creditBefore) });

  // 3. a real pool
  const name = "e2e pool " + Date.now();
  await page.getByLabel("Name", { exact: true }).fill(name);
  await page.getByLabel("Claim period (seconds)").fill("600");
  await page.getByLabel("Pool (GEN sent now)").fill("0.05");
  await page.getByRole("button", { name: "Create pool and lock GEN" }).click();
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 15 * 60_000 });
  await shot(page, "03-pool-created");
  let pool = null;
  for (let off = 0; ; ) {
    const pg = await view(page, "get_pools", [off, 50, Math.floor(Date.now() / 1000)]);
    pool = pg.items.find((p) => p.name === name && p.sponsor === w.address.toLowerCase()) ?? pool;
    if (pg.next_offset < 0) break;
    off = pg.next_offset;
  }
  expect(pool).toBeTruthy();
  log("created", { pool_id: pool.pool_id, funded: pool.funded, claim_deadline: pool.claim_deadline });

  // 4. file a real sandwiched swap: the victim is refunded in the same transaction
  const before = await balance(CASE.victim);
  await page.goto(`/pool/${pool.pool_id}?reg=demo`);
  await page.locator("#hash").fill(CASE.hash);
  await shot(page, "04-filing");
  await page.getByRole("button", { name: "File it" }).click();
  await page.waitForURL(/\/case\/ethereum\//, { timeout: 15 * 60_000 });
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Sandwiched · refunded", { timeout: 60_000 });
  await shot(page, "05-case-refunded");
  const c = await view(page, "get_pool_case", [pool.pool_id, "ethereum", CASE.hash]);
  let after = before;
  for (let i = 0; i < 30 && after - before < BigInt(c.refund_paid); i++) { await new Promise((s) => setTimeout(s, 10000)); after = await balance(CASE.victim); }
  expect(c.state).toBe("SANDWICHED_REFUNDED");
  expect(after - before).toBe(BigInt(c.refund_paid));
  log("refund_arrived", { state: c.state, refund_paid: c.refund_paid, victim_delta: String(after - before) });

  // 5. the same case again: refused by the contract
  await page.goto(`/pool/${pool.pool_id}?reg=demo`);
  await page.locator("#hash").fill(CASE.hash);
  await page.getByRole("button", { name: "File it" }).click();
  await expect(statusText(page)).toContainText(/failed|rejected/i, { timeout: 10 * 60_000 });
  await expect(statusText(page)).toContainText("ALREADY_DECIDED");
  await shot(page, "06-duplicate-refused");
  log("duplicate_refused", { status: await statusText(page).innerText() });

  // 6. after the claim period (nothing pending): close, the rest back to the sponsor wallet
  const wait = pool.claim_deadline * 1000 - Date.now() + 20_000;
  if (wait > 0) await page.waitForTimeout(wait);
  await page.goto(`/pool/${pool.pool_id}?reg=demo`);
  const sponsorBefore = await balance(w.address);
  await page.getByRole("button", { name: "Close pool" }).click();
  await expect(statusText(page)).toContainText(/accepted|finalized/i, { timeout: 15 * 60_000 });
  const closed = await view(page, "get_pool", [pool.pool_id, 0]);
  expect(closed.status).toBe("CLOSED");
  let sponsorAfter = sponsorBefore;
  for (let i = 0; i < 30 && sponsorAfter <= sponsorBefore; i++) { await new Promise((s) => setTimeout(s, 10000)); sponsorAfter = await balance(w.address); }
  await page.reload();
  await expect(page.getByText("CLOSED").first()).toBeVisible();
  await shot(page, "07-closed");
  log("closed", { returned: closed.returned, refunded: closed.refunded, funded: closed.funded, wallet_delta_after_fee: String(sponsorAfter - sponsorBefore) });
  expect(BigInt(closed.refunded) + BigInt(closed.returned)).toBe(BigInt(closed.funded));
  summary.transactions = w.sent;
  writeFileSync(new URL("summary.json", SHOTS), JSON.stringify(summary, null, 1) + "\n");
});
