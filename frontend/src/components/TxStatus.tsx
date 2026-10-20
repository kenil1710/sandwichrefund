"use client";
import type { TxProgress } from "@/lib/types";
import { explorerUrl } from "@/lib/genlayer";

export function TxStatus({ p }: { p: TxProgress | null }) {
  if (!p) return null;
  const cls = p.phase === "failed" || p.phase === "rejected" ? "note warn" : "note";
  return (
    <p className={cls} role="status" aria-live="polite">
      <b>{p.phase}</b> · {p.message}{p.hash && <> · <a href={explorerUrl("tx", p.hash)} target="_blank" rel="noreferrer">tx {p.hash.slice(0, 10)}…</a></>}
    </p>
  );
}
