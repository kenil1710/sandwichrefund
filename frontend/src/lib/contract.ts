/**
 * Browser access to the SandwichRefund contracts. Reads go through the site's
 * cached /api/view; writes are signed by the injected wallet.
 *
 * A write is not done when sent, nor when accepted: `send` reports each phase
 * and reports success only after `confirm` re-read the contract and found the
 * effect. create_pool and top_up never revert: a refusal is a successful transaction
 * returning ok:false (the GEN is credited back for withdraw_refund), shown as
 * "rejected", never as success.
 *
 * Payouts: file_case (a refund), close_pool and withdraw_refund pay with one external value
 * message. The fee must carry an External allocation naming the payee, or
 * Studio skips the payout. Studio simulates writes with a fixed clock
 * (2024-11-26), so a time-gated call can fail simulation although it would
 * succeed now: then the allocation is built by hand.
 */
import type { CalldataEncodable, TransactionHash } from "genlayer-js/types";
import { encodeExternalMessageFeeParams } from "genlayer-js";
import { NETWORK, getReadClient, getWalletClient } from "./genlayer";
import type { TxProgress, WriteResult } from "./types";

const READ_TIMEOUT_MS = 45_000;
async function withTimeout<T>(work: Promise<T>, label: string, ms = READ_TIMEOUT_MS): Promise<T> {
  let timer: ReturnType<typeof setTimeout>;
  const guard = new Promise<never>((_, reject) => { timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms / 1000}s`)), ms); });
  try { return await Promise.race([work, guard]); } finally { clearTimeout(timer!); }
}

let freshReads = 0;
/** One contract view through the site's cached /api/view, retried with exponential backoff and jitter when the
 *  relay or Studio is rate limited (429) or briefly unavailable (502/503). */
export async function viewOf<T>(address: string, fn: string, args: CalldataEncodable[] = [], fresh = false): Promise<T> {
  const q = new URLSearchParams({ a: address, f: fn, args: JSON.stringify(args, (_k, v) => (typeof v === "bigint" ? v.toString() : v)) });
  if (fresh || freshReads > 0) q.set("fresh", String(Date.now()));
  let last = "";
  for (let i = 0; i < 4; i++) {
    const r = await withTimeout(fetch(`/api/view?${q}`), fn);
    const j = await r.json().catch(() => ({ error: `HTTP ${r.status}` }));
    if (r.ok && !j.error) return (typeof j.value === "string" ? JSON.parse(j.value) : j.value) as T;
    last = j.error ?? `view ${fn} failed`;
    if (![429, 502, 503].includes(r.status) && !/rate limit|429/i.test(last)) break;
    const wait = (/rate limit|429/i.test(last) ? 6000 : 700) * 2 ** i + Math.floor(Math.random() * 300);
    await new Promise((res) => setTimeout(res, Math.min(wait, 20_000)));
  }
  throw new Error(last);
}

const STATUS_NAMES = ["PENDING", "PROPOSING", "COMMITTING", "REVEALING", "ACCEPTED", "FINALIZED", "UNDETERMINED", "CANCELED"];
function statusName(tx: unknown): string {
  const t = tx as { status?: number | string; statusName?: string };
  if (typeof t?.status === "number") return STATUS_NAMES[t.status] ?? "";
  return String(t?.statusName ?? t?.status ?? "");
}

/** The SDK's `readable` rendering drops commas between map entries; put them back. */
function repairReadable(text: string): string {
  let out = "", inString = false, escaped = false;
  for (const ch of text) {
    if (inString) { out += ch; if (escaped) escaped = false; else if (ch === "\\") escaped = true; else if (ch === '"') inString = false; continue; }
    if (ch === '"') { const prev = out.replace(/\s+$/, "").slice(-1); if (prev && !"{[,:".includes(prev)) out += ","; out += ch; inString = true; continue; }
    out += ch;
  }
  return out;
}

function returned(tx: unknown): { reverted: boolean; reason: string; body: Record<string, unknown> | null } {
  const receipt = (tx as { consensus_data?: { leader_receipt?: unknown[] } })?.consensus_data?.leader_receipt?.[0] as
    | { result?: { payload?: unknown; status?: string }; execution_result?: string } | undefined;
  const reverted = receipt?.execution_result === "ERROR" || receipt?.result?.status === "rollback";
  const payload = receipt?.result?.payload as { readable?: string } | string | undefined;
  if (reverted) return { reverted, reason: typeof payload === "string" && payload ? payload : "The contract refused this call", body: null };
  const text = typeof payload === "string" ? payload : typeof payload?.readable === "string" ? payload.readable : null;
  if (!text) return { reverted: false, reason: "", body: null };
  for (const c of [text, repairReadable(text)]) {
    try { let v: unknown = JSON.parse(c); if (typeof v === "string") v = JSON.parse(v); if (v && typeof v === "object") return { reverted: false, reason: "", body: v as Record<string, unknown> }; } catch { /* next */ }
  }
  return { reverted: false, reason: "", body: null };
}

/** The contract's own refusal text from a failed fee simulation. */
function contractRefusal(error: unknown): string | null {
  type Node = { cause?: unknown; data?: { receipt?: { result?: unknown } } };
  let node = error as Node | undefined;
  for (let depth = 0; node && depth < 6; depth++, node = node.cause as Node | undefined) {
    const result = node?.data?.receipt?.result;
    const encoded = typeof result === "string" ? result : typeof (result as { payload?: unknown })?.payload === "string" ? (result as { payload: string }).payload : null;
    if (!encoded) continue;
    try {
      const bytes = Uint8Array.from(atob(encoded), (c) => c.charCodeAt(0));
      let start = 0;
      while (start < bytes.length && bytes[start] < 0x20) start++;
      const text = new TextDecoder().decode(bytes.subarray(start)).trim();
      if (text) return text;
    } catch { /* not base64 */ }
  }
  return null;
}

const EXT_GAS = 500_000n;
type Alloc = { messageType: unknown; recipient: unknown; budget?: unknown };
const hasPayout = (fees: { messageAllocations?: Alloc[] } | undefined, who: string) =>
  Boolean(fees?.messageAllocations?.some((a) => Number(a.messageType) === 0 && String(a.recipient).toLowerCase() === who.toLowerCase() && BigInt(String(a.budget ?? 0)) > 0n));
/** Refusals that only reflect the simulator's fixed 2024 clock. */
const CLOCK_ONLY = /TOO_EARLY_UNTIL|CLAIM_PERIOD_OPEN_UNTIL|SENDS_MAY_BE_PENDING|CLAIM_PERIOD_OVER/;

async function feesFor(wallet: ReturnType<typeof getWalletClient>, address: `0x${string}`, fn: string, args: CalldataEncodable[], value: bigint, payee: string | null) {
  let est: Awaited<ReturnType<typeof wallet.estimateTransactionFeesForWrite>> | null = null;
  try {
    est = await withTimeout(wallet.estimateTransactionFeesForWrite({ address, functionName: fn, args, value }), "fee estimate", 30_000);
  } catch (e) {
    const refusal = contractRefusal(e);
    if (refusal && !CLOCK_ONLY.test(refusal)) throw new Error(refusal);
  }
  if (!payee) return est ?? withTimeout(wallet.estimateTransactionFees({}), "fee estimate", 30_000);
  if (est && hasPayout(est, payee)) return est;
  const price = (BigInt(est?.policy?.receiptGasPrice ?? 300_000_000n) * 12n) / 10n;
  const messageAllocations = [{ messageType: 0, recipient: payee, budget: EXT_GAS * price, onAcceptance: false,
    feeParams: encodeExternalMessageFeeParams({ gasLimit: EXT_GAS, maxGasPrice: price }) }];
  const fees = await withTimeout(wallet.estimateTransactionFees({ messageAllocations } as never), "fee estimate", 30_000);
  if (!hasPayout(fees, payee)) throw new Error("The payout could not be funded; nothing was sent.");
  return fees;
}

export interface SendOptions<T> {
  /** the address this call pays (file_case, close_pool, withdraw_refund): its External allocation is attached */
  payee?: string | null;
  confirm?: (body: T | null) => Promise<boolean>;
  onProgress?: (p: TxProgress) => void;
}

export async function send<T>(account: `0x${string}`, address: string, fn: string, args: CalldataEncodable[], value = 0n,
    opts: SendOptions<T> = {}): Promise<WriteResult<T>> {
  const report = (p: TxProgress) => opts.onProgress?.(p);
  const wallet = getWalletClient(account);
  const read = getReadClient();
  let hash: string;
  report({ phase: "signing", hash: null, message: "Waiting for your wallet to sign." });
  try {
    const fees = await feesFor(wallet, address as `0x${string}`, fn, args, value, opts.payee ?? null);
    hash = await wallet.writeContract({ address: address as `0x${string}`, functionName: fn, args, value, ...(fees ? { fees } : {}) } as never);
  } catch (e) {
    const message = String((e as Error)?.message ?? e);
    const funding = /insufficient|exceeds balance|not enough/i.test(message)
      ? (NETWORK === "studiodev" ? "This wallet does not hold enough GEN for the value and the fee. Fund it from the Studio Dev faucet." : "Not enough GEN.") : null;
    const error = contractRefusal(e) ?? funding ?? message;
    report({ phase: "failed", hash: null, message: error });
    return { kind: "failed", hash: null, error };
  }
  report({ phase: "submitted", hash, message: "Submitted. Validators are processing it; every validator reads the case from two Ethereum RPCs, which takes a minute or two." });
  const started = Date.now();
  let tx: unknown = null;
  for (;;) {
    await new Promise((r) => setTimeout(r, 4000));
    try { tx = await read.getTransaction({ hash: hash as TransactionHash }); } catch { /* keep polling */ }
    const name = statusName(tx);
    if (name === "ACCEPTED" || name === "FINALIZED") break;
    if (name === "UNDETERMINED") { const error = "The validators did not agree, so nothing was written. It can be sent again."; report({ phase: "failed", hash, message: error }); return { kind: "failed", hash, error }; }
    if (name === "CANCELED") { report({ phase: "failed", hash, message: "The transaction was canceled." }); return { kind: "failed", hash, error: "The transaction was canceled." }; }
    if (Date.now() - started > 900_000) { const error = "Not accepted within 15 minutes. It may still land; check the explorer."; report({ phase: "failed", hash, message: error }); return { kind: "failed", hash, error }; }
  }
  const r = returned(tx);
  if (r.reverted) { report({ phase: "failed", hash, message: r.reason }); return { kind: "failed", hash, error: r.reason }; }
  if (r.body && r.body.ok === false) { const reason = String(r.body.reason ?? "The contract turned this down"); report({ phase: "rejected", hash, message: reason }); return { kind: "rejected", hash, reason }; }
  if (opts.confirm) {
    report({ phase: "accepted", hash, message: "Accepted. Re-reading the contract to confirm." });
    let ok = false;
    for (let i = 0; i < 6 && !ok; i++) {
      freshReads++;
      try { ok = await opts.confirm(r.body as T | null); } catch { ok = false; } finally { freshReads--; }
      if (!ok) await new Promise((res) => setTimeout(res, 4000));
    }
    if (!ok) { const error = "Accepted, but the contract state does not show the change yet."; report({ phase: "failed", hash, message: error }); return { kind: "failed", hash, error }; }
  }
  report({ phase: "accepted", hash, message: "Accepted and confirmed in contract state. Payouts arrive when the transaction finalizes." });
  void (async () => {
    for (let i = 0; i < 120; i++) {
      await new Promise((res) => setTimeout(res, 10_000));
      try { if (statusName(await read.getTransaction({ hash: hash as TransactionHash })) === "FINALIZED") { report({ phase: "finalized", hash, message: "Finalized." }); return; } } catch { /* wait */ }
    }
  })();
  return { kind: "ok", hash, data: (r.body ?? {}) as T };
}
