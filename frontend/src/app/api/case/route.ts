/** GET /api/case?chain=ethereum&hash=0x…[&reg=demo] -> the case (every pool's decision) and MEVGate's reading, JSON. */
import { asReg, gateAddr, regAddr } from "@/lib/deployments";
import { gateCase, getCase } from "@/lib/server";

export const dynamic = "force-dynamic";

export async function GET(req: Request) {
  const u = new URL(req.url);
  const chain = (u.searchParams.get("chain") ?? "ethereum").toLowerCase();
  const hash = (u.searchParams.get("hash") ?? "").toLowerCase();
  const reg = asReg(u.searchParams.get("reg"));
  if (!/^0x[0-9a-f]{64}$/.test(hash)) return Response.json({ error: "hash must be 0x + 64 hex" }, { status: 400 });
  try {
    const [c, gate] = await Promise.all([getCase(regAddr(reg), chain, hash), gateCase(gateAddr(reg), chain, hash)]);
    return Response.json({ contract: regAddr(reg), gate_contract: gateAddr(reg), case: c, gate },
      { headers: { "cache-control": "public, s-maxage=30, stale-while-revalidate=120", "access-control-allow-origin": "*" } });
  } catch (e) {
    return Response.json({ error: "Studio Dev unreadable: " + String((e as Error)?.message ?? e).slice(0, 200) }, { status: 502 });
  }
}
