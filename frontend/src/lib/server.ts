/**
 * Server-side reads from Studio Dev (pages and API routes). Every number on
 * the site comes from one of these views or from the keeper's status file on
 * the keeper-state branch; nothing is cached longer than the page's
 * revalidate window.
 */
import "server-only";
import { createClient } from "genlayer-js";
import { studioDevnet } from "genlayer-js/chains";
import type { Attacker, Case, GateAddress, GateCase, Page, Pool, Stats } from "./types";
import { REPO } from "./deployments";

const client = createClient({ chain: studioDevnet });

export function plain(v: unknown): unknown {
  if (v instanceof Map) return Object.fromEntries([...v.entries()].map(([k, x]) => [String(k), plain(x)]));
  if (Array.isArray(v)) return v.map(plain);
  if (typeof v === "bigint") return Number(v) <= Number.MAX_SAFE_INTEGER ? Number(v) : v.toString();
  return v;
}

/** Studio meters reads per IP per minute: identical reads within 15 s are served once per instance. */
const memo = new Map<string, { at: number; value: unknown }>();
const MEMO_MS = 15_000;

export async function view<T>(address: string, fn: string, args: unknown[] = []): Promise<T> {
  const key = `${address.toLowerCase()}|${fn}|${JSON.stringify(args)}`;
  const hit = memo.get(key);
  if (hit && Date.now() - hit.at < MEMO_MS) return hit.value as T;
  let last: unknown;
  for (let i = 0; i < 5; i++) {
    try {
      const r = await client.readContract({ address: address as `0x${string}`, functionName: fn, args: args as never });
      const value = (typeof r === "string" ? JSON.parse(r) : plain(r)) as T;
      if (memo.size > 2000) memo.clear();
      memo.set(key, { at: Date.now(), value });
      return value;
    } catch (e) {
      last = e;
      const limited = /rate limit|-32029|429/i.test(String((e as Error)?.message ?? e));
      await new Promise((res) => setTimeout(res, limited ? 12_000 : 900 * (i + 1)));
    }
  }
  throw last;
}

async function walk<T>(address: string, fn: string, pre: unknown[], post: unknown[] = []): Promise<T[]> {
  const out: T[] = [];
  for (let off = 0; ; ) {
    const p = await view<Page<T>>(address, fn, [...pre, off, 50, ...post]);
    out.push(...(p.items ?? []));
    if (p.next_offset === -1 || p.next_offset === undefined || p.next_offset <= off) return out;
    off = p.next_offset;
  }
}

const now = () => Math.floor(Date.now() / 1000);
export const allPools = (reg: string) => walk<Pool>(reg, "get_pools", [], [now()]);
export const allCases = (reg: string) => walk<Case>(reg, "get_cases", []);
export const allAttackers = (reg: string) => walk<Attacker>(reg, "get_attackers", []);
export const poolCases = (reg: string, pid: number) => walk<Case>(reg, "get_pool_cases", [pid]);
export const victimCases = (reg: string, a: string) => walk<Case>(reg, "get_victim", [a]);
export const pool = (reg: string, pid: number) => view<Pool>(reg, "get_pool", [pid, now()]);
export const getCase = (reg: string, chain: string, hash: string) => view<Case>(reg, "get_case", [chain, hash]);
export const stats = (reg: string) => view<Stats>(reg, "get_stats", []);
export const config = (reg: string) => view<Record<string, unknown>>(reg, "get_config", []);
export const gateCase = (gate: string, chain: string, hash: string) => view<GateCase>(gate, "check_case", [chain, hash]);
export const gateAddress = (gate: string, a: string) => view<GateAddress>(gate, "check_address", [a]);

/** eth_getBalance on Studio Dev, wei. */
export async function balanceOf(address: string): Promise<bigint> {
  const r = await fetch(studioDevnet.rpcUrls.default.http[0], { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "eth_getBalance", params: [address, "latest"] }), cache: "no-store" });
  const j = await r.json();
  return BigInt(j.result ?? "0x0");
}

export interface KeeperAction { key: string; kind: string; pool_id: number; hash?: string; status: string; result: string; tx: string; attempts: number; last_error: string; why: string }
export interface KeeperStatus {
  keeper: string; started_at: string; finished_at: string; trigger: string; run_url: string;
  contracts: Record<string, { address: string; last_run: Record<string, number>; totals: Record<string, unknown>;
    pools: Record<string, { chains: Record<string, { cursor: number; failed: number[]; pages_ok: number; done: boolean; head: number }>; status: string; claim_deadline: number; name: string }>;
    unprocessed: { key: string; why: string }[]; actions: KeeperAction[] }>;
  history: { started_at: string; finished_at: string; trigger: string; run_url: string; runs: Record<string, Record<string, number>> }[];
}

/** The keeper's status.json on the keeper-state branch (raw GitHub, revalidated every minute). */
export async function keeperStatus(): Promise<KeeperStatus | null> {
  const raw = REPO.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/keeper-state/status.json";
  try {
    const r = await fetch(raw, { next: { revalidate: 60 } });
    if (!r.ok) return null;
    return (await r.json()) as KeeperStatus;
  } catch {
    return null;
  }
}

/** case tx hash -> the GenLayer transaction that filed it (from the keeper's state), canonical contract. */
export async function filingTxs(): Promise<Record<string, string>> {
  const s = await keeperStatus();
  const out: Record<string, string> = {};
  for (const c of Object.values(s?.contracts ?? {})) for (const a of c.actions ?? []) if (a.kind === "FILE" && a.hash && a.tx && a.status === "DONE") out[`${a.pool_id}:${a.hash}`] = a.tx;
  return out;
}
