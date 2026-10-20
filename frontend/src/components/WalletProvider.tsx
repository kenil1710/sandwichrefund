"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  useSyncExternalStore,
} from "react";
import {
  CHAIN_ID_HEX,
  NETWORK_LABEL,
  ensureCorrectNetwork,
  getReadClient,
  getWalletChainId,
  hasInjectedWallet,
  requestAccount,
} from "@/lib/genlayer";

interface WalletState {
  account: `0x${string}` | null;
  balance: bigint | null;
  chainId: string | null;
  onWrongNetwork: boolean;
  hasWallet: boolean;
  connecting: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => void;
  switchNetwork: () => Promise<void>;
  refreshBalance: () => Promise<void>;
}

const WalletContext = createContext<WalletState | null>(null);

/** Remembers the connection across reloads so a refresh does not log you out. */
const STORAGE_KEY = "sandwichrefund.connected";

export function WalletProvider({ children }: { children: React.ReactNode }) {
  const [account, setAccount] = useState<`0x${string}` | null>(null);
  const [balance, setBalance] = useState<bigint | null>(null);
  const [chainId, setChainId] = useState<string | null>(null);
  const [connecting, setConnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /**
   * Whether an injected wallet exists, read through useSyncExternalStore.
   *
   * `window.ethereum` is external state that does not exist during SSR, so it
   * cannot be a `useState` initialiser, and setting it from an effect makes
   * React render twice for a value that was knowable on the first client pass.
   * The server snapshot is `false`, which is also the honest answer there.
   * Extensions inject before hydration and do not come and go afterwards, so
   * there is nothing to subscribe to.
   */
  const hasWallet = useSyncExternalStore(
    () => () => {},
    () => hasInjectedWallet(),
    () => false,
  );

  const refreshBalance = useCallback(async () => {
    if (!account) return setBalance(null);
    try {
      setBalance(await getReadClient().getBalance({ address: account }));
    } catch {
      setBalance(null);
    }
  }, [account]);

  useEffect(() => {
    // Pulling the balance from the chain when the account changes is exactly
    // the "subscribe to an external system" case the rule allows; the setState
    // happens in the async continuation, not synchronously in the effect body,
    // but the rule cannot see through the promise.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refreshBalance();
  }, [refreshBalance]);

  useEffect(() => {
    if (!account) return;
    void getWalletChainId().then(setChainId);
  }, [account]);

  /**
   * Connect, then move the wallet onto this network.
   *
   * TWO PROMPTS, AND THE SECOND ONE MAY BE DECLINED WITHOUT LOSING THE FIRST.
   * `ensureCorrectNetwork` asks the wallet to switch — and to ADD the network
   * first if it has never heard of it (error 4902) — so an approved connection
   * normally lands on the right chain with no further clicking.
   *
   * It used to be awaited BEFORE the account was committed, which meant
   * declining the switch threw, skipped `setAccount`, and left the person
   * disconnected entirely under the message "You dismissed the wallet prompt."
   * They had dismissed a different prompt, and the one thing they had actually
   * approved was discarded. The account is now committed first and a refused
   * switch is reported as what it is: connected, wrong network, one button from
   * being right — and `onWrongNetwork` already puts that button in the header,
   * on the register form, on the challenge form and on the operator panel.
   */
  const connect = useCallback(async () => {
    setConnecting(true);
    setError(null);
    try {
      const next = await requestAccount();
      setAccount(next);
      window.localStorage.setItem(STORAGE_KEY, "1");
      try {
        await ensureCorrectNetwork();
      } catch (e) {
        const message = e instanceof Error ? e.message : String(e);
        setError(
          /User rejected|4001/i.test(message)
            ? `Connected, but your wallet is on another network. Use “Switch to ${NETWORK_LABEL}” to finish.`
            : message,
        );
      }
      setChainId(await getWalletChainId());
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      setError(/User rejected|4001/i.test(message) ? "You dismissed the wallet prompt." : message);
    } finally {
      setConnecting(false);
    }
  }, []);

  const disconnect = useCallback(() => {
    setAccount(null);
    setBalance(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const switchNetwork = useCallback(async () => {
    try {
      await ensureCorrectNetwork();
      setChainId(await getWalletChainId());
      setError(null);
    } catch (e) {
      const message = e instanceof Error ? e.message : String(e);
      // Say which network, and that nothing is lost by trying again. The raw
      // "User rejected the request." names neither.
      setError(
        /User rejected|4001/i.test(message)
          ? `Still on another network — SandwichRefund reads and writes on ${NETWORK_LABEL} only.`
          : message,
      );
    }
  }, []);

  /**
   * Silent reconnect. `eth_accounts` does NOT prompt — it returns whatever the
   * wallet has already authorised for this origin, so a page load restores the
   * session without throwing a popup at someone who only came to read.
   */
  useEffect(() => {
    if (typeof window === "undefined" || !window.ethereum) return;
    if (window.localStorage.getItem(STORAGE_KEY) !== "1") return;
    void window.ethereum
      .request({ method: "eth_accounts" })
      .then((result) => {
        const accounts = result as string[];
        if (accounts?.length) setAccount(accounts[0] as `0x${string}`);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    const provider = window.ethereum;
    if (!provider?.on) return;
    const onAccounts = (...args: unknown[]) => {
      const accounts = args[0] as string[];
      setAccount(accounts?.length ? (accounts[0] as `0x${string}`) : null);
    };
    const onChain = (...args: unknown[]) => setChainId(String(args[0]).toLowerCase());
    provider.on("accountsChanged", onAccounts);
    provider.on("chainChanged", onChain);
    return () => {
      provider.removeListener?.("accountsChanged", onAccounts);
      provider.removeListener?.("chainChanged", onChain);
    };
  }, []);

  const value = useMemo<WalletState>(
    () => ({
      account,
      balance,
      chainId,
      onWrongNetwork: Boolean(account && chainId && chainId !== CHAIN_ID_HEX.toLowerCase()),
      hasWallet,
      connecting,
      error,
      connect,
      disconnect,
      switchNetwork,
      refreshBalance,
    }),
    [account, balance, chainId, hasWallet, connecting, error, connect, disconnect, switchNetwork, refreshBalance],
  );

  return <WalletContext.Provider value={value}>{children}</WalletContext.Provider>;
}

export function useWallet(): WalletState {
  const context = useContext(WalletContext);
  if (!context) throw new Error("useWallet must be used inside <WalletProvider>");
  return context;
}
