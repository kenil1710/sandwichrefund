/** GET /api/verify -> every deployed contract's on-chain code vs the build file on GitHub at its deploy commit. */
import { verifyAll } from "@/lib/verify";
import { COMMIT } from "@/lib/deployments";

export const dynamic = "force-dynamic";

export async function GET() {
  const rows = await verifyAll();
  return Response.json({ commit: COMMIT, one_commit: new Set(rows.map((r) => r.commit)).size === 1, ok: rows.every((r) => r.identical), rows },
    { headers: { "cache-control": "public, s-maxage=300, stale-while-revalidate=600" } });
}
