"use client";
import { useWallet } from "./WalletProvider";
import { NETWORK_LABEL } from "@/lib/genlayer";

export function WalletButton() {
  const w = useWallet();
  if (!w.hasWallet) return <span className="small">Read-only (no wallet)</span>;
  if (!w.account) return <button className="btn ghost" onClick={() => void w.connect()} disabled={w.connecting}>{w.connecting ? "Connecting…" : "Connect wallet"}</button>;
  if (w.onWrongNetwork) return <button className="btn" onClick={() => void w.switchNetwork()}>Switch to {NETWORK_LABEL}</button>;
  return <span className="mono small" title={w.account}>{w.account.slice(0, 6)}…{w.account.slice(-4)}</span>;
}
