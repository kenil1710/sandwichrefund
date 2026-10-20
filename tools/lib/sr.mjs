// A SandwichRefund client for scripts (seeds, demo, keeper): one signer, one
// contract, settle-aware writes (test/harness.mjs) and payouts funded the way
// Studio delivers them (tools/lib/payout.mjs).
import { readFileSync, existsSync } from "node:fs";
import { connect, gen, returnedJson } from "../../test/harness.mjs";
import { payoutFees, payoutDelivered, manualAllocation } from "./payout.mjs";

const root = new URL("../../", import.meta.url);
export const STUDIO_RPC = "https://studio-dev.genlayer.com/api";
export const EXPLORER = "https://explorer-studio-dev.genlayer.com";

export function deployments(set = "final") {
  const p = new URL(set === "final" ? "deployments.json" : `deployments.${set}.json`, root);
  return existsSync(p) ? JSON.parse(readFileSync(p, "utf8")) : { contracts: {} };
}

/** eth_getBalance on Studio Dev (wei, BigInt). */
export async function balanceOf(address) {
  for (let i = 0; i < 6; i++) {
    try {
      const r = await fetch(STUDIO_RPC, { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getBalance", params: [address, "latest"] }), signal: AbortSignal.timeout(20000) });
      const j = await r.json();
      if (j.result) return BigInt(j.result);
    } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 3000 * (i + 1)));
  }
  throw new Error("eth_getBalance unreadable for " + address);
}

const toObj = (v) => (typeof v === "string" ? JSON.parse(v) : v);
export const plain = (v) => JSON.parse(JSON.stringify(v, (k, x) => (typeof x === "bigint" ? x.toString() : x instanceof Map ? Object.fromEntries(x) : x)));

/** Fees for a call that may pay `payee`, built by hand (no simulation): the External allocation for the payee. */
export async function manualPayoutFees(wallet, payee) {
  const price = 360_000_000n;
  const est = await wallet.estimateTransactionFees({ messageAllocations: [manualAllocation(payee, price)] });
  return { distribution: est.distribution, ...(est.messageAllocations ? { messageAllocations: est.messageAllocations } : {}), feeValue: est.feeValue };
}

/** role: a key in test/.accounts.json (or SANDWICH_<ROLE>_KEY); address: the contract. */
export function client({ role, address }) {
  const c = connect({ address, role });
  const me = c.account.address;
  async function view(fn, args = []) { return plain(toObj(await c.view(fn, args))); }
  /** A write. payee: the address this call may pay - the fee then carries its External allocation.
   *  simulate=false builds the allocation by hand (calls that read the web or depend on the clock). */
  async function write(fn, args = [], { value = 0n, payee = null, simulate = true } = {}) {
    let fees;
    if (payee) {
      try { fees = simulate ? await payoutFees(c.wallet, { address, functionName: fn, args, payee }) : await manualPayoutFees(c.wallet, payee); }
      catch (e) { return { ok: false, status: "NOT_SENT", hash: null, reason: "fee estimate failed: " + String(e?.details ?? e?.shortMessage ?? e?.message ?? e).slice(0, 160) }; }
    }
    const out = await c.send(fn, args, value, fees ? { fees } : {});
    return { ok: out.ok, status: out.status, hash: out.hash, reason: out.revertReason ?? "", returned: (out.ok ? returnedJson(out) : null) ?? out.returned, seconds: out.seconds, tx: out.tx };
  }
  return { me, view, write, read: c.read, wallet: c.wallet };
}

/** Wait until a tx is FINALIZED (or a terminal failure); returns the tx. */
export async function finalized(read, hash, { timeoutMs = 1_800_000 } = {}) {
  const t0 = Date.now();
  for (;;) {
    let tx = null;
    try { tx = plain(await read.getTransaction({ hash })); } catch { /* blind poll */ }
    if (tx?.statusName === "FINALIZED") return tx;
    if (["CANCELED", "UNDETERMINED"].includes(tx?.statusName)) return tx;
    if (Date.now() - t0 > timeoutMs) return tx;
    await new Promise((r) => setTimeout(r, 15000));
  }
}

export { payoutDelivered, gen };
