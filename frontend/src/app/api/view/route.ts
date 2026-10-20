/**
 * GET /api/view?a=<contract>&f=<view method>&args=<json array>
 * One SandwichRefund / MEVGate view, read server-side from Studio Dev, cached
 * by the CDN for 20 s (Studio meters per IP; every visitor shares this
 * deployment's). Only view methods of the four deployed contracts are served.
 */
import { ADDR } from "@/lib/deployments";
import { view } from "@/lib/server";

export const dynamic = "force-dynamic";
const ALLOWED = new Set(Object.values(ADDR).map((a) => a.toLowerCase()));

export async function GET(req: Request) {
  const u = new URL(req.url);
  const a = u.searchParams.get("a") ?? "";
  const f = u.searchParams.get("f") ?? "";
  let args: unknown[] = [];
  try { args = JSON.parse(u.searchParams.get("args") ?? "[]"); } catch { return Response.json({ error: "bad args" }, { status: 400 }); }
  if (!ALLOWED.has(a.toLowerCase()) || !/^(get_|check_case$|check_address$|is_clean$|was_refunded$|latest_attestation$)/.test(f) || !Array.isArray(args) || args.length > 4) {
    return Response.json({ error: "not a SandwichRefund view" }, { status: 400 });
  }
  try {
    const value = await view(Object.values(ADDR).find((x) => x.toLowerCase() === a.toLowerCase())!, f, args);
    return Response.json({ value }, { headers: { "cache-control": u.searchParams.has("fresh") ? "no-store" : "public, s-maxage=20, stale-while-revalidate=120" } });
  } catch (e) {
    return Response.json({ error: String((e as Error)?.message ?? e).slice(0, 300) }, { status: 502, headers: { "cache-control": "no-store" } });
  }
}
