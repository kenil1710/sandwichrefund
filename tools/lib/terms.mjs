// Pool terms -> the per-chain shape judge() reads (the same as chain_terms in contracts/SandwichRefund.py).
export function chainTerms(pool, chain) {
  const r = (pool.ranges ?? []).find((x) => x.chain === chain) ?? { start_block: 0, end_block: -1 };
  const rates = {};
  for (const x of pool.rates ?? []) if (x.chain === chain) rates[x.token.toLowerCase()] = [BigInt(x.num), BigInt(x.den)];
  return { chain, routers: (pool.routers ?? []).filter((x) => x.chain === chain).map((x) => x.address.toLowerCase()),
    kinds: pool.kinds, start_block: Number(r.start_block), end_block: Number(r.end_block), rates };
}
