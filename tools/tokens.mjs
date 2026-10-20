// data/tokens.json: symbol and decimals of every token in docs/feasibility.json, read from Ethereum (display only).
//   node tools/tokens.mjs
import { readFileSync, writeFileSync } from "node:fs";
import { rpcSend } from "./lib/sandwich.mjs";
import { CHAINS } from "./lib/chains.mjs";

const root = new URL("../", import.meta.url);
const feas = JSON.parse(readFileSync(new URL("docs/feasibility.json", root)));
const toks = new Set();
for (const c of feas.cases) for (const p of c.pools ?? []) { toks.add(p.token0); toks.add(p.token1); }
const list = [...toks].sort();
const calls = list.flatMap((t) => [["eth_call", [{ to: t, data: "0x95d89b41" }, "latest"]], ["eth_call", [{ to: t, data: "0x313ce567" }, "latest"]]]);
const out = {};
for (let i = 0; i < list.length; i += 6) {
  const part = list.slice(i, i + 6);
  let r;
  try { r = await rpcSend(CHAINS.ethereum.rpcs[0], calls.slice(2 * i, 2 * i + 12)); } catch { r = null; }
  part.forEach((t, k) => {
    let sym = "", dec = 18;
    if (r) {
      const s = String(r[2 * k] ?? "0x"), d = String(r[2 * k + 1] ?? "0x");
      try {
        if (s.length >= 194) { const len = parseInt(s.slice(66, 130), 16); sym = Buffer.from(s.slice(130, 130 + 2 * len), "hex").toString("utf8"); }
        else if (s.length === 66) sym = Buffer.from(s.slice(2), "hex").toString("utf8").replace(/\0+$/, "");
      } catch { sym = ""; }
      if (d.length > 2) dec = Number(BigInt(d));
    }
    out[t] = { symbol: sym.replace(/[^\x20-\x7e]/g, "").slice(0, 16) || t.slice(0, 8), decimals: dec };
  });
}
writeFileSync(new URL("data/tokens.json", root), JSON.stringify(out, null, 1) + "\n");
console.log(Object.keys(out).length, "tokens");
