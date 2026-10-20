import type { Case } from "@/lib/types";
import { short, tokenDec, tokenSym, units } from "@/lib/format";

/**
 * The block timeline: the sandwich drawn as three stacked bars in transaction
 * order - the front-run (red), the victim (navy), the back-run (red) - each
 * with its transaction index and the amounts the pool recorded. Bar length is
 * the X token (the victim's input) moved, on a square-root scale.
 */
export function Timeline({ c }: { c: Case }) {
  const f = c.facts ?? {};
  const d = f.direction ?? 0;
  const X = f.token_in ?? "", Y = f.token_out ?? "";
  const xi = d === 0 ? "n0" : "n1", yi = d === 0 ? "n1" : "n0";
  const get = (p: string, k: string) => BigInt(((f as Record<string, unknown>)[`${p}_${k}`] as string) ?? "0");
  const abs = (v: bigint) => (v < 0n ? -v : v);
  const rows: { label: string; who: string; idx: number | undefined; x: bigint; y: bigint; color: string; text: string }[] = [];
  const hasPair = f.front_index !== undefined;
  if (hasPair) rows.push({ label: "FRONT-RUN", who: short(f.attacker_eoa ?? ""), idx: f.front_index, x: get("front", xi), y: get("front", yi), color: "#e5484d", text: "#fff" });
  rows.push({ label: "VICTIM", who: short(c.victim), idx: c.tx_index, x: get("victim", xi), y: get("victim", yi), color: "#0e1a3a", text: "#fff" });
  if (hasPair) rows.push({ label: "BACK-RUN", who: short(f.attacker_eoa ?? ""), idx: f.back_index, x: get("back", xi), y: get("back", yi), color: "#e5484d", text: "#fff" });
  const max = rows.reduce((m, r) => (abs(r.x) > m ? abs(r.x) : m), 1n);
  const sqrt = (v: bigint) => Math.sqrt(Number(v) / Number(max));
  const W = 760, H = 64 + rows.length * 74, left = 118, span = W - left - 24;
  const fmt = (v: bigint, t: string) => `${v > 0n ? "paid" : "got"} ${units(abs(v), tokenDec(t))} ${tokenSym(t)}`;
  return (
    <svg className="timeline" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`Block ${c.block}: ${rows.map((r) => `${r.label} at index ${r.idx}: ${fmt(r.x, X)}, ${fmt(r.y, Y)}`).join("; ")}`}>
      <text x="16" y="28" fontFamily="var(--font-mono)" fontSize="12" fill="#47526e">BLOCK {c.block} · POOL {short(c.dex_pool)} ({f.kind ?? ""})</text>
      <line x1={left - 30} y1="44" x2={left - 30} y2={H - 14} stroke="#0e1a3a" strokeWidth="2" />
      {rows.map((r, i) => {
        const y = 52 + i * 74;
        const w = Math.max(14, sqrt(abs(r.x)) * span);
        return (
          <g key={r.label}>
            <circle cx={left - 30} cy={y + 18} r="5" fill={r.color} />
            <text x="16" y={y + 15} fontFamily="var(--font-mono)" fontSize="11" fill="#47526e">tx idx</text>
            <text x="16" y={y + 32} fontFamily="var(--font-display)" fontWeight="700" fontSize="20" fill="#0e1a3a">#{r.idx}</text>
            <rect x={left} y={y} width={w} height="36" fill={r.color} rx="2" />
            <text x={left + 10} y={y + 23} fontFamily="var(--font-mono)" fontSize="12" fontWeight="700" fill={r.text}>{r.label}</text>
            <text x={left} y={y + 54} fontFamily="var(--font-mono)" fontSize="11.5" fill="#0e1a3a">{r.who} · {fmt(r.x, X)} · {fmt(r.y, Y)}</text>
          </g>
        );
      })}
    </svg>
  );
}
