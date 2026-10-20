import type { Metadata } from "next";
import { SponsorForm } from "./SponsorForm";

export const metadata: Metadata = { title: "Sponsor a pool" };

export default function Sponsor() {
  return (
    <>
      <p className="kicker" style={{ marginTop: 28 }}>Sponsor dashboard</p>
      <h1>Fund a refund pool</h1>
      <p className="lede">A wallet, a DEX front-end or a protocol locks GEN for the users of its routers. The terms freeze when you send: you can add GEN and move the deadline later, never cancel. When the claim period ends anyone closes the pool and what is left comes back to you.</p>
      <p className="note warn">A pool that covers blocks still to come can be farmed by someone who sandwiches a second wallet of their own: set the rate so a refund is worth less than the profit it repays, and keep the caps small. A pool whose block range is already in the past cannot be farmed.</p>
      <SponsorForm />
    </>
  );
}
