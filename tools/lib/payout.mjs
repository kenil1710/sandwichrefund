// Payouts on Studio Dev, the way that delivers.
//
// The registry pays with one external value message (an EthSend, posted by
// gl.evm.Account(payee).emit_call(amount, b"")). Its fee comes from the
// caller's message allocation: one External allocation naming the payee,
// budget = gasLimit * maxGasPrice. payoutFees() makes sure the claim carries
// exactly that, and refuses to submit a claim that would not; payoutDelivered()
// reads the finalized transaction and says whether the value really arrived
// (not skipped), and checkBalances() whether the balances moved by it.
//
// An internal emit_transfer is the thing NOT to use: Studio stores it with
// declared budget 0, marks it skipped and credits the value back to the
// contract (measured on Studio Dev).
import { createRequire } from "node:module";
const require = createRequire(new URL("../../test/package.json", import.meta.url));
const { encodeAbiParameters } = require("viem");

export const EXTERNAL = 0;                 // genlayer-js MessageType.External
export const EXT_GAS_LIMIT = 500_000n;     // Studio's default_external_gas_limit

const lc = (a) => String(a ?? "").toLowerCase();
const big = (v) => BigInt(v ?? 0);

export function encodeExternalFeeParams(gasLimit, maxGasPrice) {
  return encodeAbiParameters([{ type: "tuple", components: [{ name: "gasLimit", type: "uint256" }, { name: "maxGasPrice", type: "uint256" }] }],
    [{ gasLimit, maxGasPrice }]);
}

/** The External allocation that funds a payout to `payee`, or null. */
export function externalAllocation(fees, payee) {
  for (const a of fees?.messageAllocations ?? []) {
    if (Number(a.messageType) === EXTERNAL && lc(a.recipient) === lc(payee) && big(a.budget) > 0n) return a;
  }
  return null;
}

/** "" if `fees` fund a payout to `payee`, else why not. */
export function payoutFeesProblem(fees, payee) {
  const a = externalAllocation(fees, payee);
  if (!a) return "no External message allocation for the payee";
  const total = big(fees?.distribution?.totalMessageFees);
  if (total < big(a.budget)) return `totalMessageFees ${total} below the allocation budget ${a.budget}`;
  if (big(fees?.feeValue) < total) return `feeValue ${fees?.feeValue} below totalMessageFees ${total}`;
  return "";
}

/** An allocation built by hand, for when the simulation does not return one. */
export function manualAllocation(payee, maxGasPrice) {
  return { messageType: EXTERNAL, recipient: payee, budget: EXT_GAS_LIMIT * maxGasPrice,
    feeParams: encodeExternalFeeParams(EXT_GAS_LIMIT, maxGasPrice), onAcceptance: false };
}

/** Fees for `functionName` on `address` that fund a payout to `payee`. Throws rather than return fees that do not.
 *  Studio simulates a write with a fixed clock (2024-11-26T06:42:42Z, measured), so a call that is only allowed
 *  after a deadline (settle, refund_unclaimed) cannot be simulated: then the allocation is built by hand. */
export async function payoutFees(wallet, { address, functionName = "claim", args = [], payee }) {
  const pick = (e) => ({ distribution: e.distribution, ...(e.messageAllocations ? { messageAllocations: e.messageAllocations } : {}), feeValue: e.feeValue });
  let est = null, fees = null;
  try { est = await wallet.estimateTransactionFeesForWrite({ address, functionName, args, value: 0n }); fees = pick(est); } catch { est = null; }
  if (!fees || payoutFeesProblem(fees, payee)) {
    const price = (est ? big(est.policy?.receiptGasPrice) * 12n / 10n : 0n) || 360_000_000n;
    est = await wallet.estimateTransactionFees({ messageAllocations: [manualAllocation(payee, price)] });
    fees = pick(est);
  }
  const why = payoutFeesProblem(fees, payee);
  if (why) throw new Error("payout not funded: " + why);
  return fees;
}

/**
 * Did this finalized transaction deliver `amount` to `payee`?
 * tx: genlayer-js getTransaction() (bigints already stringified is fine).
 * -> { ok, why, netFee }  netFee: what the sender paid (deposit - refund)
 */
export function payoutDelivered(tx, payee, amount) {
  const want = big(amount);
  if (tx?.statusName !== "FINALIZED") return { ok: false, why: `status ${tx?.statusName}` };
  const msg = (tx.messages ?? []).find((m) => lc(m.recipient) === lc(payee) && big(m.value) === want);
  if (!msg) return { ok: false, why: "no message to the payee for the amount" };
  const fa = tx.data?.fee_accounting ?? {};
  const effects = Object.entries(fa.message_value_effects ?? {}).filter(([, e]) => big(e.value) === want);
  if (effects.length !== 1) return { ok: false, why: `${effects.length} value effects for the amount` };
  const [key, e] = effects[0];
  if (e.skipped) return { ok: false, why: `skipped (declaredBudget ${e.declaredBudget}), value credited back to the contract` };
  if (fa.message_effect_delivered?.[key] !== true) return { ok: false, why: "effect not delivered" };
  // the sender paid its deposit, got back the refund and the external send's unused gas reservation
  const extBack = (fa.external_message_fee_payouts ?? []).filter((x) => lc(x.recipient) === lc(tx.from_address ?? tx.sender ?? payee))
    .reduce((s, x) => s + big(x.amount), 0n);
  return { ok: true, why: "", netFee: big(fa.paid_fee_value) - big(fa.total_refunded) - extBack };
}

/** Balances before/after the claim: the contract lost exactly `amount`; the payee gained `amount - netFee` when it sent the claim itself. */
export function checkBalances({ contractBefore, contractAfter, payeeBefore, payeeAfter, amount, netFee, payeeSent = true }) {
  const a = big(amount);
  const c = big(contractBefore) - big(contractAfter);
  const p = big(payeeAfter) - big(payeeBefore);
  const expect = payeeSent ? a - big(netFee) : a;
  if (c !== a) return `contract balance moved by ${-c}, expected -${a}`;
  if (p !== expect) return `payee balance moved by ${p}, expected ${expect}`;
  return "";
}
