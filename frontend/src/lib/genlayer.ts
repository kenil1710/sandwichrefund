/**
 * GenLayer client setup for SandwichRefund.
 *
 *   - `getReadClient()`   — no signer, for `@gl.public.view` methods. Safe anywhere.
 *   - `getWalletClient()` — browser-only, signs via an injected EIP-1193 wallet.
 */
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";

/**
 * Next inlines `process.env.NEXT_PUBLIC_*` at build time only for *literal*
 * member access — `process.env[name]` silently yields undefined in the browser.
 * Hence the literal reads below rather than a lookup helper.
 */
const rawNetwork = process.env.NEXT_PUBLIC_NETWORK;

/**
 * Always use the SDK's built-in chain definitions rather than hand-rolling a
 * chain object: they carry the consensus/staking/fee-manager addresses and
 * `isStudio`, which the SDK needs to poll transactions. A hand-written
 * `{ id, name, rpcUrls }` omits all of that and breaks receipt polling.
 */
const CHAINS = { studiodev: studioDevnet } as const;

export type NetworkName = keyof typeof CHAINS;

function resolveNetwork(value: string | undefined): NetworkName {
  if (!value) return "studiodev";
  if (value in CHAINS) return value as NetworkName;
  throw new Error(
    `NEXT_PUBLIC_NETWORK must be one of ${Object.keys(CHAINS).join(" | ")}, got: ${value}`,
  );
}

export const NETWORK = resolveNetwork(rawNetwork);
export const chain = CHAINS[NETWORK];

/** Studio is gasless — a 0 GEN balance still needs funding to STAKE, though. */
export const IS_GASLESS = Boolean(chain.isStudio);

/** `chain.id` as the hex string EIP-1193 expects. Derived, never transcribed. */
export const CHAIN_ID_HEX = `0x${chain.id.toString(16)}`;

export const NETWORK_LABEL: string = { studiodev: "Studio Dev" }[NETWORK];

/**
 * The SDK's `studioDevnet` carries no `blockExplorers` entry, so the explorer
 * base is named here rather than derived. A missing one is not cosmetic: it
 * would send MetaMask an entry with no explorer and make `explorerUrl()` emit
 * bare paths like `/tx/0x…`.
 */
export const EXPLORER_BASE = "https://explorer-studio-dev.genlayer.com";

const WALLET_NETWORK: Record<NetworkName, { name: string; explorer?: string }> = {
  studiodev: { name: "GenLayer Studio Dev", explorer: EXPLORER_BASE },
};

function addChainParams() {
  const profile = WALLET_NETWORK[NETWORK];
  const explorer = profile.explorer ?? chain.blockExplorers?.default?.url;
  return {
    chainId: CHAIN_ID_HEX,
    chainName: profile.name,
    rpcUrls: [...chain.rpcUrls.default.http],
    nativeCurrency: {
      name: chain.nativeCurrency.name,
      symbol: chain.nativeCurrency.symbol,
      decimals: chain.nativeCurrency.decimals,
    },
    // Omitted rather than sent empty: MetaMask rejects a malformed entry.
    ...(explorer ? { blockExplorerUrls: [explorer] } : {}),
  };
}

/** Minimal EIP-1193 shape — avoids depending on wallet-specific typings. */
export type EthereumProvider = {
  request(args: { method: string; params?: unknown[] }): Promise<unknown>;
  on?(event: string, handler: (...args: unknown[]) => void): void;
  removeListener?(event: string, handler: (...args: unknown[]) => void): void;
};

declare global {
  interface Window {
    ethereum?: EthereumProvider;
  }
}

export function hasInjectedWallet(): boolean {
  return typeof window !== "undefined" && Boolean(window.ethereum);
}

export async function getWalletChainId(): Promise<string | null> {
  if (!hasInjectedWallet()) return null;
  try {
    const id = await window.ethereum!.request({ method: "eth_chainId" });
    return typeof id === "string" ? id.toLowerCase() : null;
  } catch {
    return null;
  }
}

export async function addNetworkToWallet(): Promise<void> {
  if (!hasInjectedWallet()) throw new Error("No injected wallet found. Install MetaMask to continue.");
  await window.ethereum!.request({ method: "wallet_addEthereumChain", params: [addChainParams()] });
}

/** Switch the wallet to this network, adding it first if unknown (error 4902). */
export async function switchToNetwork(): Promise<void> {
  if (!hasInjectedWallet()) throw new Error("No injected wallet found. Install MetaMask to continue.");
  try {
    await window.ethereum!.request({
      method: "wallet_switchEthereumChain",
      params: [{ chainId: CHAIN_ID_HEX }],
    });
  } catch (error) {
    if ((error as { code?: number })?.code !== 4902) throw error;
    await addNetworkToWallet();
  }
}

export type Deployment = "canonical" | "demo";
const DEPLOYMENT_KEY = "sandwichrefund-contract";

/** Which registry the app talks to: canonical (real cases, 1 h claim period) or demo (minutes). Per browser. */
export function getDeployment(): Deployment {
  if (typeof window === "undefined") return "canonical";
  try {
    return window.localStorage.getItem(DEPLOYMENT_KEY) === "demo" ? "demo" : "canonical";
  } catch {
    return "canonical";
  }
}

export function setDeployment(d: Deployment): void {
  try {
    window.localStorage.setItem(DEPLOYMENT_KEY, d);
  } catch { /* storage blocked: stays canonical */ }
}

/**
 * Same-origin relay for Studio, implemented at `app/api/rpc/route.ts`.
 *
 * Studio serves CORS headers on success but drops them on its 429s, so an
 * exhausted rate limit reaches the browser as "No 'Access-Control-Allow-Origin'
 * header is present" rather than as the rate-limit error it is. Going through
 * our own origin means the browser is always allowed to read the response.
 */
const STUDIO_PROXY_PATH = "/api/rpc";

/**
 * Browser-only, deliberately: the relay path is relative, and a relative URL is
 * not a legal `fetch` target in Node. During SSR the direct URL is also simply
 * correct — server-side requests have no same-origin policy to trip over.
 */
function rpcUrl(): string {
  const direct = chain.rpcUrls.default.http[0];
  if (!IS_GASLESS || typeof window === "undefined") return direct;
  return STUDIO_PROXY_PATH;
}

/**
 * A COPY of the chain, never the SDK's exported singleton.
 *
 * `genlayer-js` treats `createClient({ endpoint })` as license to mutate
 * `chain.rpcUrls.default.http` in place, and this module also hands the same
 * chain object to `addChainParams()`. Writing the relay path onto the singleton
 * would feed MetaMask `"/api/rpc"` as a network's RPC URL, producing a wallet
 * entry that cannot reach anything.
 */
function clientChain() {
  const url = rpcUrl();
  if (url === chain.rpcUrls.default.http[0]) return chain;
  return {
    ...chain,
    rpcUrls: { ...chain.rpcUrls, default: { ...chain.rpcUrls.default, http: [url] } },
  };
}

let readClient: ReturnType<typeof createClient> | null = null;

/** Read-only client for view methods. No account, so it can never sign. */
export function getReadClient() {
  readClient ??= createClient({ chain: clientChain() });
  return readClient;
}

export function getWalletClient(account: `0x${string}`) {
  if (typeof window === "undefined") {
    throw new Error("getWalletClient is browser-only; guard it behind an effect.");
  }
  const provider = window.ethereum;
  if (!provider) throw new Error("No injected wallet found. Install MetaMask to send transactions.");
  return createClient({ chain: clientChain(), provider, account });
}

export async function requestAccount(): Promise<`0x${string}`> {
  if (!hasInjectedWallet()) throw new Error("No injected wallet found. Install MetaMask to continue.");
  const accounts = (await window.ethereum!.request({ method: "eth_requestAccounts" })) as string[];
  if (!accounts?.length) throw new Error("Wallet returned no accounts.");
  return accounts[0] as `0x${string}`;
}

export async function ensureCorrectNetwork(): Promise<void> {
  if (!hasInjectedWallet()) return;
  await switchToNetwork();
}

export function explorerUrl(kind: "tx" | "address", value: string): string {
  const base = (chain.blockExplorers?.default?.url ?? EXPLORER_BASE).replace(/\/$/, "");
  return `${base}/${kind}/${value}`;
}
