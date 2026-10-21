export interface Page<T> { total: number; offset: number; limit: number; items: T[]; next_offset: number }

export interface Facts {
  pool?: string; kind?: string; direction?: number; token_in?: string; token_out?: string;
  victim_n0?: string; victim_n1?: string; front_tx?: string; front_index?: number; back_tx?: string; back_index?: number;
  attacker_eoa?: string; attacker_contract?: string; attacker_recipient?: string;
  front_n0?: string; front_n1?: string; back_n0?: string; back_n1?: string; hops?: number; attackers?: number; others?: number;
}

export interface Case {
  found?: boolean; case_id: number; chain: string; tx_hash: string; pool_id: number; filer: string; filed_at: number;
  attempts: number; state: string; final: boolean; verdict: string; reason: string; detail: string; block: number;
  tx_index: number; victim: string; router: string; dex_pool: string; facts: Facts; profit_token: string; loss: string;
  refund_due: string; refund_paid: string; limit: string; attacker: string;
  n_decisions?: number; decisions?: Case[]; refund_paid_all_pools?: string; pools_on_chain?: number;
}

export interface Pool {
  found?: boolean; pool_id: number; sponsor: string; name: string; meta: Record<string, unknown>; status: string;
  chains: string[]; routers: { chain: string; address: string; name: string }[]; kinds: string[];
  ranges: { chain: string; start_block: number; end_block: number }[];
  rates: { chain: string; token: string; num: string; den: string; symbol: string; decimals: number }[];
  max_per_swap: string; max_per_victim: string; claim_period_s: number; created_at: number; claim_deadline: number;
  original_deadline: number; funded: string; balance: string; refunded: string; returned: string; n_cases: number;
  n_refunded: number; n_unpaid: number; closed_at: number; closed_by: string; history: Record<string, unknown>[]; due: string;
  recovery_deadline: number; pending: number; n_expired: number;
}

export interface Attacker { address: string; contract: string; n_cases: number; refunds: string; last_case: number; first_case: number }

export interface Stats {
  pools: number; cases: number; attackers: number; counts: Record<string, number>; received_total: string; open_total: string;
  refunded_total: string; returned_total: string; credit_owed_total: string; credit_paid_total: string; stray_swept_total: string;
  loss_total: Record<string, string>; held: string; balance: string;
}

export interface GateCase {
  chain: string; tx_hash: string; state: string; final: boolean; clean: boolean; refunded: boolean; refund_paid: string;
  loss: string; profit_token: string; victim: string; attacker: string; pool_id: number; sponsor: string; case_id: number; reason: string; why: string;
}

export interface GateAddress { address: string; pool_id: number; sponsor: string; state: string; cases: number; counts: Record<string, number>; refunded: string; loss_cases: number; clean: boolean; why: string }

export type TxPhase = "signing" | "submitted" | "accepted" | "finalized" | "rejected" | "failed";
export interface TxProgress { phase: TxPhase; hash: string | null; message: string }
export type WriteResult<T> = { kind: "ok"; hash: string; data: T } | { kind: "rejected"; hash: string; reason: string } | { kind: "failed"; hash: string | null; error: string };
