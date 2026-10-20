// stdin: [{terms, r}] -> stdout: [judge(terms, r)] with the keeper's mirror of the rule (test_meaning.py).
import { judge } from "../tools/lib/sandwich.mjs";
let s = "";
for await (const c of process.stdin) s += c;
const items = JSON.parse(s);
const out = items.map(({ terms, r }) => {
  const rates = {};
  for (const [k, v] of Object.entries(terms.rates)) rates[k] = v.map(BigInt);
  return judge({ ...terms, rates }, r);
});
process.stdout.write(JSON.stringify(out, (k, v) => (typeof v === "bigint" ? v.toString() : v)));
