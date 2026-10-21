import type { Metadata } from "next";
import { GateDemo } from "./GateDemo";
import { ADDR, CANONICAL } from "@/lib/deployments";

export const metadata: Metadata = { title: "MEVGate" };

export default function Gate() {
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Consumer contract</p>
      <h1>MEVGate</h1>
      <p className="lede">What another contract asks before it acts on a swap or an address: a wallet&apos;s rebate program, a front-end&apos;s reputation score, an insurance cover. Every question names the pool and the sponsor the consumer trusts, so a copycat pool is never read. Structured states, never favorable on missing data.</p>
      <pre className="mono small" style={{ background: "var(--receipt)", color: "var(--receipt-ink)", padding: 14, overflowX: "auto" }}>{`gate = gl.contract.get_at(Address("${ADDR.gate}")).view()
POOL, SPONSOR = ${CANONICAL.pool_id}, "${CANONICAL.sponsor}"    # the pool you trust, and who funds it
s = gate.check_case(POOL, SPONSOR, "ethereum", tx_hash)
# NO_POOL | NOT_COVERED | CLEAN | SANDWICHED_REFUNDED | SANDWICHED_UNPAID | UNCLEAR | UNVERIFIABLE | EXPIRED
if s["clean"]:      ...   # true only for a final CLEAN decision of that pool
if s["refunded"]:   ...   # true only when that pool paid a refund
a = gate.check_address(POOL, SPONSOR, address)   # counts per state, refunded total, worst state`}</pre>
      <GateDemo />
    </>
  );
}
