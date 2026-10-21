/** GET /api/badge?chain=ethereum&hash=0x… or ?address=0x… [&pool=<id>&sponsor=0x…][&reg=demo] -> an SVG badge with
 *  MEVGate's state for the named pool (the canonical one unless named). */
import { asReg, CANONICAL, gateAddr } from "@/lib/deployments";
import { gateAddress, gateCase } from "@/lib/server";
import { gen } from "@/lib/format";

export const dynamic = "force-dynamic";
const COLORS: Record<string, string> = { SANDWICHED_REFUNDED: "#00c2a8", SANDWICHED_UNPAID: "#e5484d", CLEAN: "#0e1a3a", UNCLEAR: "#b7861f" };
const esc = (s: string) => s.replace(/[<>&"']/g, "");

function svg(left: string, right: string, color: string) {
  const lw = 6 + left.length * 6.6, rw = 10 + right.length * 6.6;
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${lw + rw}" height="20" role="img" aria-label="${esc(left)}: ${esc(right)}"><title>${esc(left)}: ${esc(right)}</title><rect width="${lw}" height="20" fill="#111214"/><rect x="${lw}" width="${rw}" height="20" fill="${color}"/><g fill="#fff" font-family="ui-monospace,Menlo,monospace" font-size="11"><text x="5" y="14">${esc(left)}</text><text x="${lw + 5}" y="14">${esc(right)}</text></g></svg>`;
}

export async function GET(req: Request) {
  const u = new URL(req.url);
  const reg = asReg(u.searchParams.get("reg"));
  const hash = (u.searchParams.get("hash") ?? "").toLowerCase();
  const address = (u.searchParams.get("address") ?? "").toLowerCase();
  let right = "UNVERIFIABLE", color = "#6b7280";
  const pid = Number(u.searchParams.get("pool") ?? CANONICAL.pool_id), sponsor = (u.searchParams.get("sponsor") ?? CANONICAL.sponsor).toLowerCase();
  try {
    if (/^0x[0-9a-f]{64}$/.test(hash)) {
      const g = await gateCase(gateAddr(reg), pid, sponsor, (u.searchParams.get("chain") ?? "ethereum").toLowerCase(), hash);
      right = g.state === "SANDWICHED_REFUNDED" ? `REFUNDED ${gen(g.refund_paid)} GEN` : g.state;
      color = COLORS[g.state] ?? color;
    } else if (/^0x[0-9a-f]{40}$/.test(address)) {
      const g = await gateAddress(gateAddr(reg), pid, sponsor, address);
      right = `${g.state} · ${g.cases} cases · ${gen(g.refunded)} GEN`;
      color = COLORS[g.state] ?? color;
    } else right = "BAD QUERY";
  } catch { right = "UNREADABLE"; }
  return new Response(svg("sandwichrefund", right, color), { headers: { "content-type": "image/svg+xml", "cache-control": "public, s-maxage=60, stale-while-revalidate=300" } });
}
