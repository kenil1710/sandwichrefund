/** GET /api/address?address=0x…[&reg=demo] -> MEVGate's reading of the address and every case it sent, JSON. */
import { asReg, gateAddr, regAddr } from "@/lib/deployments";
import { gateAddress, victimCases } from "@/lib/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const u = new URL(req.url);
  const a = (u.searchParams.get("address") ?? "").toLowerCase();
  const reg = asReg(u.searchParams.get("reg"));
  if (!/^0x[0-9a-f]{40}$/.test(a)) return Response.json({ error: "address must be 0x + 40 hex" }, { status: 400 });
  try {
    const [gate, cases] = await Promise.all([gateAddress(gateAddr(reg), a), victimCases(regAddr(reg), a)]);
    return Response.json({ address: a, contract: regAddr(reg), gate_contract: gateAddr(reg), gate, cases },
      { headers: { "cache-control": "public, s-maxage=30, stale-while-revalidate=120", "access-control-allow-origin": "*" } });
  } catch (e) {
    return Response.json({ error: "Studio Dev unreadable: " + String((e as Error)?.message ?? e).slice(0, 200) }, { status: 502 });
  }
}
