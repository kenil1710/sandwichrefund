// Written by tools/sync_frontend.mjs from deployments.json.
import dep from "./deployments.json";
export const COMMIT: string = dep.commit;
export const ADDR = { registry: dep.registry, registryDemo: dep.registryDemo, gate: dep.gate, gateDemo: dep.gateDemo };
export const CONTRACTS: Record<string, { address: string; file: string; sha256: string; bytes: number; commit: string; deploy_tx: string; constructor_args: unknown[] }> = dep.contracts;
export const STUDIO_EXPLORER = "https://explorer-studio-dev.genlayer.com";
export const REPO = "https://github.com/kenil1710/sandwichrefund";
export const SITE = "https://sandwichrefund.vercel.app";
import binding from "./binding.json";
/** The canonical pool and its sponsor: what the site's MEVGate reads are bound to unless a reader names another. */
export const CANONICAL = { pool_id: binding.pool_id, sponsor: binding.sponsor };
export type Reg = "canonical" | "demo";
export const regAddr = (r: Reg) => (r === "demo" ? ADDR.registryDemo : ADDR.registry);
export const gateAddr = (r: Reg) => (r === "demo" ? ADDR.gateDemo : ADDR.gate);
export const asReg = (v: unknown): Reg => (v === "demo" ? "demo" : "canonical");
