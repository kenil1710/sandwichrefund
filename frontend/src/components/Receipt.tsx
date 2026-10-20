import Link from "next/link";
import type { Case } from "@/lib/types";
import { gen, short, STATE_LABEL, tokenDec, tokenSym, units, routerName } from "@/lib/format";

export function stampClass(state: string) {
  return state === "SANDWICHED_REFUNDED" ? "mint" : state === "SANDWICHED_UNPAID" ? "red" : "grey";
}

function Row({ k, v, title }: { k: string; v: React.ReactNode; title?: string }) {
  return <div className="row"><span className="k">{k}</span><span className="dots" aria-hidden="true" /><span className="v" title={title}>{v}</span></div>;
}

/** A thermal-print receipt for one case. */
export function Receipt({ c, reg = "canonical", big = false, link = true }: { c: Case; reg?: string; big?: boolean; link?: boolean }) {
  const sandwiched = c.state.startsWith("SANDWICHED");
  const body = (
    <>
      <div className="head">SANDWICHREFUND · ETHEREUM</div>
      <div className="title">CASE #{String(c.case_id).padStart(4, "0")} · POOL {c.pool_id}</div>
      <Row k="TX" v={short(c.tx_hash, 8)} title={c.tx_hash} />
      <Row k="BLOCK" v={`${c.block} / idx ${c.tx_index}`} />
      <Row k="ROUTER" v={routerName(c.router) || short(c.router)} title={c.router} />
      <Row k="VICTIM" v={short(c.victim)} title={c.victim} />
      {sandwiched && <Row k="ATTACKER" v={short(c.attacker)} title={c.attacker} />}
      {sandwiched && c.facts?.front_index !== undefined && <Row k="FRONT/BACK" v={`idx ${c.facts.front_index} / ${c.facts.back_index}`} />}
      <div className="rule" />
      {sandwiched && <Row k="LOSS EST." v={`${units(c.loss, tokenDec(c.profit_token))} ${tokenSym(c.profit_token)}`} />}
      {sandwiched && <Row k="DUE" v={`${gen(c.refund_due)} GEN`} />}
      {sandwiched && c.limit && <Row k="LIMIT" v={c.limit} />}
      <Row k="REASON" v={c.reason} />
      <div className="total"><span>REFUND</span><span>{gen(c.refund_paid)} GEN</span></div>
      <div style={{ textAlign: "center" }}><span className={`stamp ${stampClass(c.state)}`}>{STATE_LABEL[c.state] ?? c.state}</span></div>
      <div className="barcode" aria-hidden="true" />
      <div className="head" style={{ marginTop: 6 }}>DECIDED BY CODE · READ FROM 2 RPCS</div>
    </>
  );
  const cls = `receipt${big ? " big" : ""}`;
  if (!link) return <div className={cls} role="group" aria-label={`Case ${c.case_id}: ${STATE_LABEL[c.state] ?? c.state}`}>{body}</div>;
  return <Link className={cls} href={`/case/${c.chain}/${c.tx_hash}${reg === "demo" ? "?reg=demo" : ""}`} aria-label={`Case ${c.case_id}: ${STATE_LABEL[c.state] ?? c.state}, refund ${gen(c.refund_paid)} GEN`}>{body}</Link>;
}
