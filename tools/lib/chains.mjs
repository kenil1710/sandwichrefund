// The chain table, the same as CHAINS / FACTORIES in contracts/shared/common.py
// (test_meaning checks they match). Two RPCs per chain, run by different
// operators, both serving logs and receipts for old blocks.
export const CHAINS = {
  ethereum: { id: 1, rpcs: ["https://rpc.mevblocker.io", "https://eth-mainnet.public.blastapi.io"], explorer: "https://etherscan.io" },
};

// The keeper's scan endpoints: these answer eth_getLogs by topic alone over a block range.
export const SCAN_RPCS = {
  ethereum: ["https://rpc.mevblocker.io", "https://eth-mainnet.public.blastapi.io", "https://eth.drpc.org"],
};

export const SWAP_V2 = "0xd78ad95fa46c994b6551d0da85fc275fe613ce37657fb8d5e3d130840159d822";
export const SWAP_V3 = "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67";

// Factories whose pools count as genuine (a look-alike pool emitting the same Swap event is refused).
export const FACTORIES = {
  ethereum: {
    V2: ["0x5c69bee701ef814a2b6a3edd4b1652cb9cc5aa6f", "0xc0aee478e3658e2610c5f7a4a2e1777ce9e4f2ac"],
    V3: ["0x1f98431c8ad98523631ae4a59f267346ea31f984"],
  },
};
