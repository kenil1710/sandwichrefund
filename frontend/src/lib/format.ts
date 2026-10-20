import tokens from "./tokens.json";
import labels from "./labels.json";
import poolCanonical from "./pool_canonical.json";

const TOK = tokens as Record<string, { symbol: string; decimals: number }>;
const LAB = labels as Record<string, string>;
const ROUTERS: Record<string, string> = Object.fromEntries(poolCanonical.routers.map((r) => [r.address.toLowerCase(), r.name]));

export const short = (a: string | undefined | null, n = 6) => (a ? `${a.slice(0, n + 2)}…${a.slice(-4)}` : "");
export const tokenSym = (t: string) => TOK[t?.toLowerCase()]?.symbol ?? short(t, 4);
export const tokenDec = (t: string) => TOK[t?.toLowerCase()]?.decimals ?? 18;
export const label = (a: string) => LAB[a?.toLowerCase()] ?? "";
export const routerName = (a: string) => ROUTERS[a?.toLowerCase()] ?? "";
export const ETHERSCAN = "https://etherscan.io";

/** A wei-like integer string as a decimal with at most `sig` significant digits. */
export function units(v: string | bigint | number | undefined, decimals = 18, sig = 4): string {
  if (v === undefined || v === null || v === "") return "0";
  let n = BigInt(v);
  const neg = n < 0n;
  if (neg) n = -n;
  const base = 10n ** BigInt(decimals);
  const whole = n / base;
  const frac = (n % base).toString().padStart(decimals, "0");
  let s: string;
  if (whole >= 1000n) s = whole.toLocaleString("en-US");
  else if (whole > 0n) s = `${whole}.${frac.slice(0, Math.max(0, sig - whole.toString().length))}`.replace(/\.?0+$/, "");
  else {
    const lead = frac.search(/[1-9]/);
    s = lead < 0 ? "0" : `0.${frac.slice(0, lead + sig)}`.replace(/0+$/, "");
  }
  return (neg ? "-" : "") + s;
}

export const gen = (wei: string | bigint | undefined) => units(wei ?? "0", 18, 4);

export function when(epoch: number): string {
  if (!epoch) return "";
  return new Date(epoch * 1000).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

export const STATE_LABEL: Record<string, string> = {
  SANDWICHED_REFUNDED: "Sandwiched · refunded",
  SANDWICHED_UNPAID: "Sandwiched · unpaid",
  CLEAN: "Clean",
  UNCLEAR: "Unclear",
  NOT_COVERED: "Not covered",
  UNVERIFIABLE: "Unverifiable",
  NO_POOL: "No pool",
};

export const REASON_TEXT: Record<string, string> = {
  SAME_POOL_SANDWICH: "A front-run and a back-run by one actor on the victim's pool, in the same block, with a net profit for the attacker.",
  NO_PATTERN: "No front-run / back-run pair by one actor on the victim's pool in its block.",
  MULTI_HOP_VICTIM: "The swap went through several pools and one of them shows a sandwich pattern: ruled unclear, not paid.",
  MULTIPLE_VICTIMS: "One front/back pair brackets several victims' swaps (a bundle): the profit cannot be split by rule.",
  MULTIPLE_ATTACKERS: "More than one attacker formed front/back pairs around this swap.",
  COMPLEX_PATTERN: "One attacker used several front-runs or back-runs.",
  PARTIAL_PATTERN: "One actor traded the pool before and after the victim, but not as a sandwich (wrong directions).",
  CROSS_BLOCK_PATTERN: "A front-run in this block is answered by a back-run in the next block.",
  NO_ATTACKER_PROFIT: "A front/back pair exists, but the attacker's net is not positive under the conservative count.",
  PROFIT_TOKEN_NOT_PRICED: "The attacker profited in a token this pool has no rate for.",
  SELF_SANDWICH: "The victim is linked to the attacker (same EOA or a shared contract): refused.",
  VICTIM_DIRECTION_UNREADABLE: "The victim's swap has no clear direction.",
  TOO_MANY_HOPS: "More than 4 pools in the victim transaction.",
  BLOCK_TOO_BUSY: "More than 40 other transactions on the victim's pools in its block.",
  ROUTER_NOT_COVERED: "The transaction did not go to a router this pool covers.",
  OUTSIDE_BLOCK_RANGE: "The block is outside the pool's range.",
  TX_FAILED: "The victim transaction failed.",
  NO_SWAP_IN_TX: "No Uniswap V2 / V3 swap in the transaction.",
  POOL_TYPE_NOT_COVERED: "The swap is on a pool type this pool does not cover.",
  POOL_NOT_CANONICAL: "The pool is not one its factory knows (a look-alike).",
  NOT_FINALIZED: "The block (or the next) is not finalized yet. File it again later.",
  RPC_UNREADABLE: "An RPC did not answer. File it again.",
  RPC_DISAGREE: "The two RPCs answered differently. File it again.",
  TX_NOT_FOUND: "Neither RPC knows this transaction.",
  TX_PENDING: "The transaction has no receipt yet.",
  WRONG_CHAIN_ID: "An RPC answered for another chain.",
};
